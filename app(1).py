# -*- coding: utf-8 -*-
"""
PyHost - نسخة مبسطة تعمل على Pydroid 3 / Python 3
ملاحظة: هذه النسخة لا تحتاج Docker، ومناسبة للتجربة المحلية.
قبل الاستخدام على الإنترنت، أضف HTTPS وحماية أقوى وعزل للمشاريع.
"""

import os
import re
import sqlite3
import secrets
import subprocess
import sys
import threading
import signal
from pathlib import Path
from functools import wraps

from flask import (
    Flask, request, redirect, url_for, session,
    render_template_string, flash, jsonify, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PROJECTS_DIR = BASE_DIR / "projects"
DB_FILE = DATA_DIR / "hosting.db"

DATA_DIR.mkdir(exist_ok=True)
PROJECTS_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin12345")

processes = {}
process_locks = {}


def get_db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = get_db()

    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            disabled INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            entrypoint TEXT DEFAULT 'main.py',
            status TEXT DEFAULT 'stopped',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    admin = con.execute(
        "SELECT id FROM users WHERE username=?",
        (ADMIN_USERNAME,)
    ).fetchone()

    if not admin:
        con.execute(
            "INSERT INTO users(username,password,is_admin) VALUES(?,?,1)",
            (
                ADMIN_USERNAME,
                generate_password_hash(ADMIN_PASSWORD)
            )
        )

    con.commit()
    con.close()


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "uid" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            abort(403)
        return func(*args, **kwargs)
    return wrapper


def make_slug(name):
    slug = re.sub(r"[^a-zA-Z0-9_-]", "-", name).strip("-").lower()
    if not slug:
        slug = "project"

    slug = slug[:40]
    return slug + "-" + secrets.token_hex(3)


def get_project(project_id):
    con = get_db()

    project = con.execute("""
        SELECT projects.*, users.username
        FROM projects
        JOIN users ON users.id = projects.user_id
        WHERE projects.id=?
    """, (project_id,)).fetchone()

    con.close()

    if not project:
        abort(404)

    if not session.get("admin") and project["user_id"] != session["uid"]:
        abort(403)

    return project


def project_folder(project):
    folder = PROJECTS_DIR / project["slug"]
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def update_status(project_id, status):
    con = get_db()
    con.execute(
        "UPDATE projects SET status=? WHERE id=?",
        (status, project_id)
    )
    con.commit()
    con.close()


def start_project(project):
    project_id = project["id"]

    if project_id in processes:
        proc = processes[project_id]
        if proc.poll() is None:
            update_status(project_id, "running")
            return

    folder = project_folder(project)
    entrypoint = project["entrypoint"]

    main_file = folder / entrypoint

    if not main_file.exists():
        raise RuntimeError(
            "ملف التشغيل غير موجود: " + entrypoint
        )

    # تشغيل Python بنفس نسخة Python الحالية.
    # stdout/stderr يتم حفظهما في logs.txt.
    log_file = folder / "logs.txt"

    log = open(log_file, "a", encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, str(main_file)],
        cwd=str(folder),
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    processes[project_id] = proc
    process_locks[project_id] = threading.Lock()
    update_status(project_id, "running")


def stop_project(project):
    project_id = project["id"]
    proc = processes.get(project_id)

    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    processes.pop(project_id, None)
    process_locks.pop(project_id, None)
    update_status(project_id, "stopped")


def refresh_status(project):
    project_id = project["id"]
    proc = processes.get(project_id)

    if proc is not None:
        if proc.poll() is None:
            return "running"

        processes.pop(project_id, None)
        update_status(project_id, "stopped")
        return "stopped"

    return project["status"]


@app.route("/")
def index():
    if "uid" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
            flash("اسم المستخدم يجب أن يكون من 3 إلى 32 حرفاً.")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("كلمة المرور يجب أن تكون 8 أحرف على الأقل.")
            return redirect(url_for("register"))

        con = get_db()

        try:
            con.execute(
                "INSERT INTO users(username,password) VALUES(?,?)",
                (username, generate_password_hash(password))
            )
            con.commit()
        except sqlite3.IntegrityError:
            flash("اسم المستخدم موجود مسبقاً.")
            con.close()
            return redirect(url_for("register"))

        con.close()

        flash("تم إنشاء الحساب بنجاح.")
        return redirect(url_for("login"))

    return render_page(
        "إنشاء حساب",
        """
        <div class="card auth">
            <h1>إنشاء حساب</h1>
            <form method="post">
                <input name="username" placeholder="اسم المستخدم" required>
                <input name="password" type="password"
                       placeholder="كلمة المرور" required>
                <button>إنشاء الحساب</button>
            </form>
            <p><a href="/login">لديك حساب؟ تسجيل الدخول</a></p>
        </div>
        """
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        con = get_db()
        user = con.execute(
            "SELECT * FROM users WHERE username=?",
            (username,)
        ).fetchone()
        con.close()

        if (
            user
            and not user["disabled"]
            and check_password_hash(user["password"], password)
        ):
            session.clear()
            session["uid"] = user["id"]
            session["username"] = user["username"]
            session["admin"] = bool(user["is_admin"])

            return redirect(url_for("dashboard"))

        flash("اسم المستخدم أو كلمة المرور غير صحيحة.")

    return render_page(
        "تسجيل الدخول",
        """
        <div class="card auth">
            <h1>PyHost</h1>
            <p>استضافة مشاريع Python</p>

            <form method="post">
                <input name="username" placeholder="اسم المستخدم" required>
                <input name="password" type="password"
                       placeholder="كلمة المرور" required>
                <button>دخول</button>
            </form>

            <p>
                ليس لديك حساب؟
                <a href="/register">إنشاء حساب</a>
            </p>
        </div>
        """
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    con = get_db()

    projects = con.execute("""
        SELECT * FROM projects
        WHERE user_id=?
        ORDER BY id DESC
    """, (session["uid"],)).fetchall()

    con.close()

    return render_page(
        "لوحة التحكم",
        """
        <h1>لوحة التحكم</h1>

        <div class="card">
            <h2>إنشاء مشروع</h2>

            <form method="post" action="/project/create">
                <input name="name"
                       placeholder="اسم المشروع"
                       required>

                <input name="entrypoint"
                       value="main.py"
                       placeholder="ملف التشغيل">

                <button>إنشاء المشروع</button>
            </form>
        </div>

        <h2>مشاريعي</h2>

        {% if projects %}
            {% for p in projects %}
                <div class="card project">
                    <div>
                        <strong>{{ p["name"] }}</strong>
                        <small>{{ p["slug"] }}</small>
                    </div>

                    <span class="{{ refresh_status(p) }}">
                        {{ refresh_status(p) }}
                    </span>

                    <a class="button"
                       href="/project/{{ p['id'] }}">
                        إدارة
                    </a>
                </div>
            {% endfor %}
        {% else %}
            <div class="card">لا توجد مشاريع.</div>
        {% endif %}
        """,
        projects=projects,
        refresh_status=refresh_status
    )


@app.route("/project/create", methods=["POST"])
@login_required
def create_project():
    name = request.form.get("name", "").strip()
    entrypoint = request.form.get(
        "entrypoint",
        "main.py"
    ).strip()

    if not name:
        flash("اكتب اسم المشروع.")
        return redirect(url_for("dashboard"))

    if not re.fullmatch(
        r"[A-Za-z0-9_.-]{1,80}",
        entrypoint
    ) or not entrypoint.endswith(".py"):
        flash("اسم ملف التشغيل غير صالح.")
        return redirect(url_for("dashboard"))

    slug = make_slug(name)

    (PROJECTS_DIR / slug).mkdir(
        parents=True,
        exist_ok=True
    )

    con = get_db()

    cursor = con.execute("""
        INSERT INTO projects(
            user_id,name,slug,entrypoint
        )
        VALUES(?,?,?,?)
    """, (
        session["uid"],
        name,
        slug,
        entrypoint
    ))

    project_id = cursor.lastrowid

    con.commit()
    con.close()

    return redirect(
        url_for("project_page", project_id=project_id)
    )


@app.route("/project/<int:project_id>")
@login_required
def project_page(project_id):
    project = get_project(project_id)
    status = refresh_status(project)

    return render_page(
        project["name"],
        """
        <h1>{{ p["name"] }}</h1>

        <div class="card">
            <p>
                الحالة:
                <strong>{{ status }}</strong>
            </p>

            <p>
                ملف التشغيل:
                <code>{{ p["entrypoint"] }}</code>
            </p>

            <div class="actions">

                <form method="post"
                      action="/project/{{ p['id'] }}/start">
                    <button>▶ تشغيل</button>
                </form>

                <form method="post"
                      action="/project/{{ p['id'] }}/stop">
                    <button>■ إيقاف</button>
                </form>

                <form method="post"
                      action="/project/{{ p['id'] }}/restart">
                    <button>↻ إعادة تشغيل</button>
                </form>

            </div>
        </div>

        <div class="card">
            <h2>رفع ملف</h2>

            <form method="post"
                  enctype="multipart/form-data"
                  action="/project/{{ p['id'] }}/upload">

                <input type="file"
                       name="file"
                       accept=".py,.zip"
                       required>

                <button>رفع</button>
            </form>

            <small>
                المسموح: Python أو ZIP.
            </small>
        </div>

        <div class="card">
            <h2>Logs</h2>

            <pre id="logs">جاري التحميل...</pre>

            <button onclick="loadLogs()">
                تحديث
            </button>
        </div>

        <script>
        async function loadLogs() {
            try {
                const response = await fetch(
                    "/project/{{ p['id'] }}/logs"
                );

                const data = await response.json();

                document.getElementById("logs").textContent =
                    data.logs || "لا توجد Logs.";
            } catch (e) {
                document.getElementById("logs").textContent =
                    "تعذر تحميل Logs.";
            }
        }

        loadLogs();
        setInterval(loadLogs, 5000);
        </script>
        """,
        p=project,
        status=status
    )


@app.route("/project/<int:project_id>/upload", methods=["POST"])
@login_required
def upload_file(project_id):
    project = get_project(project_id)

    uploaded = request.files.get("file")

    if not uploaded or not uploaded.filename:
        flash("اختر ملفاً.")
        return redirect(
            url_for("project_page", project_id=project_id)
        )

    filename = secure_filename(uploaded.filename)

    if not filename:
        flash("اسم الملف غير صالح.")
        return redirect(
            url_for("project_page", project_id=project_id)
        )

    ext = Path(filename).suffix.lower()

    if ext not in {".py", ".zip"}:
        flash("المسموح فقط .py أو .zip.")
        return redirect(
            url_for("project_page", project_id=project_id)
        )

    folder = project_folder(project)
    target = folder / filename

    uploaded.save(target)

    if ext == ".zip":
        import zipfile

        try:
            with zipfile.ZipFile(target) as archive:
                base = folder.resolve()

                for member in archive.infolist():
                    destination = (
                        folder / member.filename
                    ).resolve()

                    if not str(destination).startswith(
                        str(base) + os.sep
                    ):
                        raise ValueError(
                            "ZIP يحتوي مساراً غير آمن."
                        )

                archive.extractall(folder)

            target.unlink(missing_ok=True)

        except Exception:
            target.unlink(missing_ok=True)
            flash("ملف ZIP غير صالح.")
            return redirect(
                url_for("project_page", project_id=project_id)
            )

    flash("تم رفع الملف بنجاح.")

    return redirect(
        url_for("project_page", project_id=project_id)
    )


@app.route("/project/<int:project_id>/start", methods=["POST"])
@login_required
def start(project_id):
    project = get_project(project_id)

    try:
        start_project(project)
        flash("تم تشغيل المشروع.")
    except Exception as exc:
        flash("فشل التشغيل: " + str(exc))

    return redirect(
        url_for("project_page", project_id=project_id)
    )


@app.route("/project/<int:project_id>/stop", methods=["POST"])
@login_required
def stop(project_id):
    project = get_project(project_id)
    stop_project(project)

    flash("تم إيقاف المشروع.")

    return redirect(
        url_for("project_page", project_id=project_id)
    )


@app.route("/project/<int:project_id>/restart", methods=["POST"])
@login_required
def restart(project_id):
    project = get_project(project_id)

    try:
        stop_project(project)
        start_project(project)
        flash("تمت إعادة التشغيل.")
    except Exception as exc:
        flash("فشل التشغيل: " + str(exc))

    return redirect(
        url_for("project_page", project_id=project_id)
    )


@app.route("/project/<int:project_id>/logs")
@login_required
def logs(project_id):
    project = get_project(project_id)
    file = project_folder(project) / "logs.txt"

    if not file.exists():
        return jsonify({"logs": ""})

    try:
        text = file.read_text(
            encoding="utf-8",
            errors="replace"
        )
    except Exception:
        text = ""

    return jsonify({
        "logs": text[-15000:]
    })


@app.route("/admin")
@login_required
@admin_required
def admin():
    con = get_db()

    users = con.execute("""
        SELECT id,username,is_admin,disabled,created_at
        FROM users
        ORDER BY id DESC
    """).fetchall()

    projects = con.execute("""
        SELECT projects.*, users.username
        FROM projects
        JOIN users ON users.id=projects.user_id
        ORDER BY projects.id DESC
    """).fetchall()

    con.close()

    return render_page(
        "الإدارة",
        """
        <h1>لوحة الإدارة</h1>

        <h2>المستخدمون</h2>

        {% for u in users %}
            <div class="card project">
                <span>
                    <strong>{{ u["username"] }}</strong>
                    —
                    {% if u["disabled"] %}
                        محظور
                    {% else %}
                        فعال
                    {% endif %}
                </span>

                {% if not u["is_admin"] %}
                    <form method="post"
                          action="/admin/user/{{ u['id'] }}/toggle">
                        <button>
                            {% if u["disabled"] %}
                                فك الحظر
                            {% else %}
                                حظر
                            {% endif %}
                        </button>
                    </form>
                {% endif %}
            </div>
        {% endfor %}

        <h2>المشاريع</h2>

        {% for p in projects %}
            <div class="card project">
                <span>
                    {{ p["name"] }}
                    —
                    {{ p["username"] }}
                    —
                    {{ refresh_status(p) }}
                </span>

                <form method="post"
                      action="/admin/project/{{ p['id'] }}/stop">
                    <button>إيقاف</button>
                </form>
            </div>
        {% endfor %}
        """,
        users=users,
        projects=projects,
        refresh_status=refresh_status
    )


@app.route("/admin/user/<int:user_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_user(user_id):
    con = get_db()

    con.execute("""
        UPDATE users
        SET disabled =
            CASE disabled
                WHEN 0 THEN 1
                ELSE 0
            END
        WHERE id=? AND is_admin=0
    """, (user_id,))

    con.commit()
    con.close()

    return redirect(url_for("admin"))


@app.route("/admin/project/<int:project_id>/stop", methods=["POST"])
@login_required
@admin_required
def admin_stop(project_id):
    project = get_project(project_id)
    stop_project(project)
    return redirect(url_for("admin"))



@app.route("/project/<int:project_id>/terminal")
@login_required
def terminal_page(project_id):
    project = get_project(project_id)
    status = refresh_status(project)
    return render_page(
        "Terminal",
        """
        <h1>Terminal — {{ p["name"] }}</h1>
        <div class="card">
            <p class="hint">
                اكتب أوامر داخل مجلد المشروع. وإذا كان البرنامج ينتظر
                input()، اكتب الإجابة في خانة Input واضغط إرسال.
            </p>
            <div id="terminal" class="terminal-box"></div>

            <form id="cmdForm" class="terminal-form">
                <input id="cmd" autocomplete="off"
                       placeholder="اكتب الأمر هنا...">
                <button type="submit">تنفيذ</button>
            </form>

            <div class="terminal-actions">
                <input id="inputBox"
                       placeholder="إجابة input() للبرنامج">
                <button type="button" onclick="sendInput()">إرسال Input</button>
                <button type="button" onclick="clearTerminal()">مسح</button>
                <a class="button" href="/project/{{ p['id'] }}">رجوع</a>
            </div>
        </div>

        <script>
        const terminal = document.getElementById("terminal");

        function printLine(text, cls="") {
            const d = document.createElement("div");
            d.className = cls;
            d.textContent = text;
            terminal.appendChild(d);
            terminal.scrollTop = terminal.scrollHeight;
        }

        document.getElementById("cmdForm").addEventListener("submit", async (e) => {
            e.preventDefault();
            const box = document.getElementById("cmd");
            const command = box.value.trim();
            if (!command) return;
            box.value = "";
            printLine("> " + command, "cmdline");

            try {
                const r = await fetch("/project/{{ p['id'] }}/terminal/exec", {
                    method: "POST",
                    headers: {"Content-Type":"application/json"},
                    body: JSON.stringify({command})
                });
                const data = await r.json();
                if (data.output) printLine(data.output);
                if (data.error) printLine(data.error, "errorline");
            } catch (err) {
                printLine("خطأ في الاتصال: " + err, "errorline");
            }
            box.focus();
        });

        async function sendInput() {
            const box = document.getElementById("inputBox");
            const value = box.value;
            if (!value) return;

            try {
                const r = await fetch("/project/{{ p['id'] }}/terminal/input", {
                    method: "POST",
                    headers: {"Content-Type":"application/json"},
                    body: JSON.stringify({input:value})
                });
                const data = await r.json();
                if (data.ok) {
                    printLine("[input] " + value, "inputline");
                    box.value = "";
                } else {
                    printLine(data.error || "تعذر إرسال Input", "errorline");
                }
            } catch (err) {
                printLine("خطأ في الاتصال: " + err, "errorline");
            }
        }

        function clearTerminal() {
            terminal.innerHTML = "";
        }
        </script>
        """,
        p=project,
        status=status
    )


@app.route("/project/<int:project_id>/terminal/exec", methods=["POST"])
@login_required
def terminal_exec(project_id):
    project = get_project(project_id)
    folder = project_folder(project)
    data = request.get_json(silent=True) or {}
    command = str(data.get("command", "")).strip()

    if not command:
        return jsonify({"output":"", "error":"اكتب أمراً أولاً."})

    try:
        result = subprocess.run(
            command,
            cwd=str(folder),
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )
        return jsonify({
            "output": (result.stdout or "")[-15000:],
            "error": (result.stderr or "")[-15000:],
            "returncode": result.returncode
        })
    except subprocess.TimeoutExpired:
        return jsonify({"output":"", "error":"الأمر تجاوز 60 ثانية."}), 408
    except Exception as exc:
        return jsonify({"output":"", "error":str(exc)}), 500


@app.route("/project/<int:project_id>/terminal/input", methods=["POST"])
@login_required
def terminal_input(project_id):
    project = get_project(project_id)
    proc = processes.get(project_id)

    if proc is None or proc.poll() is not None:
        refresh_status(project)
        return jsonify({
            "ok":False,
            "error":"المشروع غير شغال. شغله أولاً."
        }), 400

    data = request.get_json(silent=True) or {}
    value = str(data.get("input", ""))

    if len(value) > 4000:
        return jsonify({
            "ok":False,
            "error":"الإدخال طويل جداً."
        }), 400

    try:
        lock = process_locks.setdefault(project_id, threading.Lock())
        with lock:
            proc.stdin.write(value + "\n")
            proc.stdin.flush()
        return jsonify({"ok":True})
    except Exception as exc:
        return jsonify({
            "ok":False,
            "error":"تعذر إرسال الإدخال: " + str(exc)
        }), 500


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "python": sys.version.split()[0]
    })


BASE_HTML = r"""
<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>{{ title or "PyHost" }}</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #0b1020;
    color: #edf2ff;
    font-family: Arial, sans-serif;
}

nav {
    min-height: 64px;
    padding: 0 6%;
    display: flex;
    align-items: center;
    gap: 20px;
    background: #11182d;
    border-bottom: 1px solid #293452;
}

nav a {
    color: white;
    text-decoration: none;
}

nav .brand {
    font-size: 22px;
    font-weight: bold;
}

nav .space {
    flex: 1;
}

main {
    width: min(1000px, 94%);
    margin: 35px auto;
}

.card {
    background: #121a30;
    border: 1px solid #293452;
    border-radius: 16px;
    padding: 20px;
    margin: 15px 0;
}

.auth {
    max-width: 430px;
    margin: 70px auto;
}

input {
    width: 100%;
    padding: 13px;
    margin: 7px 0;
    background: #080e1e;
    color: white;
    border: 1px solid #34415f;
    border-radius: 9px;
}

button,
.button {
    background: #4169e1;
    color: white;
    border: 0;
    border-radius: 9px;
    padding: 11px 16px;
    cursor: pointer;
    text-decoration: none;
    display: inline-block;
}

.project {
    display: flex;
    align-items: center;
    gap: 14px;
}

.project > div,
.project > span:first-child {
    flex: 1;
}

.project small {
    display: block;
    color: #8b98b6;
    margin-top: 5px;
}

.actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.flash {
    padding: 12px;
    margin-bottom: 12px;
    border-radius: 10px;
    background: #1d315d;
    border: 1px solid #3b5d9d;
}

pre {
    background: #060a13;
    padding: 15px;
    border-radius: 10px;
    min-height: 180px;
    overflow: auto;
    white-space: pre-wrap;
}

code {
    background: #060a13;
    padding: 3px 7px;
    border-radius: 6px;
}

a {
    color: #91b5ff;
}

@media (max-width: 650px) {
    .project {
        flex-wrap: wrap;
    }

    .project > div,
    .project > span:first-child {
        flex-basis: 100%;
    }
}
</style>
</head>

<body>

<nav>
    <a class="brand" href="/dashboard">PyHost</a>

    <span class="space"></span>

    {% if session.get("uid") %}

        {% if session.get("admin") %}
            <a href="/admin">الإدارة</a>
        {% endif %}

        <a href="/logout">خروج</a>

    {% endif %}
</nav>

<main>

{% with messages = get_flashed_messages() %}
    {% for message in messages %}
        <div class="flash">{{ message }}</div>
    {% endfor %}
{% endwith %}

{{ body|safe }}

</main>

</body>
</html>
"""


def render_page(title, body, **context):
    body_html = render_template_string(
        body,
        **context
    )

    return render_template_string(
        BASE_HTML,
        title=title,
        body=body_html
    )


init_db()


if __name__ == "__main__":
    print("=" * 50)
    print("PyHost يعمل الآن")
    print("الرابط المحلي: http://127.0.0.1:8000")
    print("اسم الأدمن:", ADMIN_USERNAME)
    print("كلمة مرور الأدمن:", ADMIN_PASSWORD)
    print("=" * 50)

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        debug=False
    )
