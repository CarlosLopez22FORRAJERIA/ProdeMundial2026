from __future__ import annotations

import os
import json
import random
import re
import secrets
import shutil
import sqlite3
import threading
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from time import sleep, time

from flask import (
    Flask,
    abort,
    flash,
    g,
    has_request_context,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from markupsafe import Markup, escape
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("PRODE_DATA_DIR", BASE_DIR))
DATABASE = Path(os.environ.get("PRODE_DATABASE", DATA_DIR / "prode.sqlite3"))
DATABASE_DIR = Path(os.environ.get("PRODE_DATABASE_DIR", DATA_DIR / "databases"))
BACKUP_DIR = Path(os.environ.get("PRODE_BACKUP_DIR", DATA_DIR / "backups"))
SECRET_KEY = os.environ.get("PRODE_SECRET_KEY", "dev-change-me")
APP_NAME = "La Fija Mundialera"
RATE_LIMITS: dict[str, list[float]] = {}
APP_TIMEZONE = timezone(timedelta(hours=-3), "ART")
MATCH_PENDING_AFTER = timedelta(hours=2)
DEFAULT_LEGAL_TEXT = """Este prode es privado y se organiza entre conocidos. La participación implica jugar de buena fe, respetar a los demás participantes y mantener un espíritu competitivo sano.

La administración puede moderar el chat, aplicar advertencias, timeouts, suspensiones o expulsiones por mala conducta dentro de la app, en el chat o fuera del sistema si afecta al grupo.

La casa se reserva el derecho de admisión y permanencia. Si un participante es expulsado por mala conducta, no corresponde devolución de lo abonado.

Los premios, porcentajes, etapas, bloqueos de carga y criterios de desempate serán administrados desde el panel correspondiente. Ante cualquier error técnico o caso no previsto, la administración resolverá buscando preservar la transparencia del juego.

Al aceptar, confirmás que leíste esta información y estás de acuerdo con participar bajo estas condiciones."""

STAGES = [
    ("fecha_1", "Fecha 1", 1, 1),
    ("fecha_2", "Fecha 2", 2, 1),
    ("fecha_3", "Fecha 3", 3, 1),
    ("r32", "16vos", 4, 1),
    ("r16", "8vos", 5, 1),
    ("qf", "4tos", 6, 0),
    ("sf", "Semis", 7, 0),
    ("final", "Final", 8, 0),
]
STAGE_ORDER = {key: order for key, _label, order, _bonus in STAGES}
KNOCKOUT_STAGE_KEYS = {key for key, _label, order, _bonus in STAGES if order >= 4}
SIDE_CHOICES = {"home", "away"}

SETTINGS_DEFAULTS = {
    "entry_price": "10000",
    "bonus_percent": "3",
    "podium_1_percent": "35",
    "podium_2_percent": "20",
    "podium_3_percent": "12",
    "podium_4_percent": "8",
    "podium_5_percent": "6",
    "podium_6_percent": "4",
    "fixture_api_url": "https://api.promiedos.com.ar/league/tables_and_fixtures/fjda",
    "promiedos_games_url_template": "https://api.promiedos.com.ar/league/games/fjda/5930_25_1_{round}",
    "promiedos_group_rounds": "1,2,3",
    "promiedos_x_ver": "1.11.7.5",
    "auto_results_enabled": "1",
    "auto_results_stage_keys": "fecha_1,fecha_2,fecha_3,r32,r16,qf,sf,final",
    "auto_results_sources": "espn,promiedos,worldcup26,upbound",
    "auto_results_interval_seconds": "30",
    "auto_results_start_before_minutes": "0",
    "auto_results_stop_after_minutes": "170",
    "auto_results_halftime_minutes": "45",
    "auto_results_halftime_retry_minutes": "20",
    "auto_results_fulltime_minutes": "90",
    "auto_results_fulltime_retry_minutes": "45",
    "auto_results_catchup_hours": "72",
    "auto_results_apply_provisional": "1",
    "auto_results_last_run_at": "",
    "auto_results_last_summary": "Todavia no corrio.",
    "auto_fixture_sync_enabled": "1",
    "auto_fixture_sync_interval_minutes": "30",
    "auto_fixture_sync_last_run_at": "",
    "auto_fixture_sync_last_summary": "Todavia no corrio.",
    "espn_scoreboard_url": "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard",
    "worldcup26_api_url": "https://worldcup26.ir/get/games",
    "upbound_worldcup_url": "https://raw.githubusercontent.com/upbound-web/worldcup-live.json/master/2026/worldcup.json",
    "chat_visible_after_id": "0",
    "legal_text": DEFAULT_LEGAL_TEXT,
    "legal_updated_at": "2026-05-10T00:00:00+00:00",
}

AUTO_RESULT_STAGE_LIMIT = {key for key, _label, _order, _bonus in STAGES}
AUTO_RESULT_SOURCES = {"promiedos", "espn", "worldcup26", "upbound"}
AUTO_RESULTS_WORKER_STARTED = False
AUTO_RESULTS_WORKER_LOCK = threading.Lock()
SCHEMA_READY_PATHS: set[Path] = set()
SCHEMA_READY_LOCK = threading.Lock()

AUTO_TEAM_ALIASES = {
    "argentina": "argentina",
    "alemania": "germany",
    "algeria": "algeria",
    "arabia saudita": "saudi arabia",
    "argelia": "algeria",
    "australia": "australia",
    "austria": "austria",
    "belgica": "belgium",
    "belgium": "belgium",
    "bosnia and herzegovina": "bosnia herzegovina",
    "bosnia herzegovina": "bosnia herzegovina",
    "brasil": "brazil",
    "brazil": "brazil",
    "cabo verde": "cape verde",
    "canada": "canada",
    "cape verde": "cape verde",
    "chile": "chile",
    "colombia": "colombia",
    "corea del sur": "south korea",
    "costa de marfil": "ivory coast",
    "cote d ivoire": "ivory coast",
    "south korea": "south korea",
    "costa rica": "costa rica",
    "croacia": "croatia",
    "croatia": "croatia",
    "curacao": "curacao",
    "curazao": "curacao",
    "czech republic": "czech republic",
    "czechia": "czech republic",
    "democratic republic of congo": "dr congo",
    "dr congo": "dr congo",
    "ecuador": "ecuador",
    "egipto": "egypt",
    "egypt": "egypt",
    "escocia": "scotland",
    "espana": "spain",
    "spain": "spain",
    "estados unidos": "united states",
    "usa": "united states",
    "united states": "united states",
    "francia": "france",
    "france": "france",
    "germany": "germany",
    "ghana": "ghana",
    "haiti": "haiti",
    "inglaterra": "england",
    "england": "england",
    "irak": "iraq",
    "iran": "iran",
    "iraq": "iraq",
    "italia": "italy",
    "italy": "italy",
    "japon": "japan",
    "japan": "japan",
    "jordania": "jordan",
    "jordan": "jordan",
    "ivory coast": "ivory coast",
    "marruecos": "morocco",
    "morocco": "morocco",
    "mexico": "mexico",
    "netherlands": "netherlands",
    "nueva zelanda": "new zealand",
    "new zealand": "new zealand",
    "noruega": "norway",
    "norway": "norway",
    "paises bajos": "netherlands",
    "panama": "panama",
    "paraguay": "paraguay",
    "portugal": "portugal",
    "qatar": "qatar",
    "rd congo": "dr congo",
    "republica checa": "czech republic",
    "saudi arabia": "saudi arabia",
    "scotland": "scotland",
    "senegal": "senegal",
    "sudafrica": "south africa",
    "south africa": "south africa",
    "suecia": "sweden",
    "sweden": "sweden",
    "suiza": "switzerland",
    "switzerland": "switzerland",
    "tunez": "tunisia",
    "tunisia": "tunisia",
    "turkey": "turkey",
    "turquia": "turkey",
    "uruguay": "uruguay",
    "uzbekistan": "uzbekistan",
}

PUBLIC_USER_ENDPOINTS = {
    "static",
    "index",
    "login",
    "logout",
    "change_password",
    "legal_info",
    "legal_accept",
}

PAGE_LABELS = {
    "dashboard": "Jugar",
    "fixture": "Fixture",
    "standings": "Tablas",
    "history": "Historico",
    "chat": "Chat",
    "admin": "Admin",
    "admin_ranking_image": "Imagen ranking",
    "legal_info": "Informacion",
    "change_password": "Clave",
}

PROMIEDOS_STAGE_MAP = {
    "fecha 1": "fecha_1",
    "fecha 2": "fecha_2",
    "fecha 3": "fecha_3",
    "16avos": "r32",
    "16avos de final": "r32",
    "8vos": "r16",
    "8vos de final": "r16",
    "octavos": "r16",
    "octavos de final": "r16",
    "4tos": "qf",
    "cuartos": "qf",
    "cuartos de final": "qf",
    "semifinal": "sf",
    "semifinales": "sf",
    "final": "final",
}

SEED_GAMES = [
    ("fecha_1", "2026-06-11 16:00", "Mexico", "Sudafrica"),
    ("fecha_1", "2026-06-11 21:00", "Canada", "Qatar"),
    ("fecha_1", "2026-06-12 16:00", "Estados Unidos", "Japon"),
    ("fecha_1", "2026-06-12 21:00", "Argentina", "Marruecos"),
    ("fecha_2", "2026-06-17 16:00", "Brasil", "Noruega"),
    ("fecha_2", "2026-06-17 21:00", "Espana", "Ghana"),
    ("fecha_2", "2026-06-18 16:00", "Francia", "Corea del Sur"),
    ("fecha_2", "2026-06-18 21:00", "Inglaterra", "Ecuador"),
    ("fecha_3", "2026-06-23 16:00", "Portugal", "Egipto"),
    ("fecha_3", "2026-06-23 21:00", "Uruguay", "Australia"),
    ("fecha_3", "2026-06-24 16:00", "Alemania", "Costa Rica"),
    ("fecha_3", "2026-06-24 21:00", "Italia", "Chile"),
    ("r32", "2026-06-28 16:00", "1A", "2B"),
    ("r32", "2026-06-28 21:00", "1C", "2D"),
    ("r16", "2026-07-04 16:00", "Ganador 16vos 1", "Ganador 16vos 2"),
    ("r16", "2026-07-04 21:00", "Ganador 16vos 3", "Ganador 16vos 4"),
    ("qf", "2026-07-09 21:00", "Ganador 8vos 1", "Ganador 8vos 2"),
    ("sf", "2026-07-14 21:00", "Ganador 4tos 1", "Ganador 4tos 2"),
    ("final", "2026-07-19 21:00", "Ganador Semi 1", "Ganador Semi 2"),
]

BRACKET_PLACEHOLDER_GAMES = [
    ("r32", "2026-06-29 17:30", "1E", "3A/B/C/D/F"),
    ("r32", "2026-06-30 18:00", "1I", "3C/D/F/G/H"),
    ("r32", "2026-06-28 16:00", "2A", "2B"),
    ("r32", "2026-06-29 22:00", "1F", "2C"),
    ("r32", "2026-07-02 20:00", "2K", "2L"),
    ("r32", "2026-07-02 16:00", "1H", "2J"),
    ("r32", "2026-07-01 21:00", "1D", "3B/E/F/I/J"),
    ("r32", "2026-07-01 17:00", "1G", "3A/E/H/I/J"),
    ("r32", "2026-06-29 14:00", "1C", "2F"),
    ("r32", "2026-06-30 14:00", "2E", "2I"),
    ("r32", "2026-06-30 22:00", "1A", "3C/E/F/H/I"),
    ("r32", "2026-07-01 13:00", "1L", "3E/H/I/J/K"),
    ("r32", "2026-07-03 19:00", "1J", "2H"),
    ("r32", "2026-07-03 15:00", "2D", "2G"),
    ("r32", "2026-07-03 00:00", "1B", "3E/F/G/I/J"),
    ("r32", "2026-07-03 22:30", "1K", "3D/E/I/J/L"),
    ("r16", "2026-07-04 18:00", "G74", "G77"),
    ("r16", "2026-07-04 14:00", "G73", "G75"),
    ("r16", "2026-07-06 16:00", "G83", "G84"),
    ("r16", "2026-07-06 21:00", "G81", "G82"),
    ("r16", "2026-07-05 17:00", "G76", "G78"),
    ("r16", "2026-07-05 21:00", "G79", "G80"),
    ("r16", "2026-07-07 13:00", "G86", "G88"),
    ("r16", "2026-07-07 17:00", "G85", "G87"),
    ("qf", "2026-07-09 17:00", "G89", "G90"),
    ("qf", "2026-07-10 16:00", "G93", "G94"),
    ("qf", "2026-07-11 18:00", "G91", "G92"),
    ("qf", "2026-07-11 22:00", "G95", "G96"),
    ("sf", "2026-07-14 16:00", "G97", "G98"),
    ("sf", "2026-07-15 16:00", "G99", "G100"),
    ("final", "2026-07-19 16:00", "G101", "G102"),
    ("final", "2026-07-18 18:00", "P101", "P102"),
]

TEAM_FLAGS = {
    "alemania": "🇩🇪",
    "arabia saudita": "🇸🇦",
    "argentina": "🇦🇷",
    "australia": "🇦🇺",
    "belgica": "🇧🇪",
    "bélgica": "🇧🇪",
    "bosnia herzegovina": "🇧🇦",
    "brasil": "🇧🇷",
    "cabo verde": "🇨🇻",
    "canada": "🇨🇦",
    "canadá": "🇨🇦",
    "chile": "🇨🇱",
    "corea del sur": "🇰🇷",
    "costa de marfil": "🇨🇮",
    "costa rica": "🇨🇷",
    "curazao": "🇨🇼",
    "ecuador": "🇪🇨",
    "egipto": "🇪🇬",
    "escocia": "🏴",
    "españa": "🇪🇸",
    "espana": "🇪🇸",
    "estados unidos": "🇺🇸",
    "francia": "🇫🇷",
    "ghana": "🇬🇭",
    "haiti": "🇭🇹",
    "haití": "🇭🇹",
    "inglaterra": "🏴",
    "iran": "🇮🇷",
    "irán": "🇮🇷",
    "italia": "🇮🇹",
    "japon": "🇯🇵",
    "japón": "🇯🇵",
    "marruecos": "🇲🇦",
    "mexico": "🇲🇽",
    "méxico": "🇲🇽",
    "noruega": "🇳🇴",
    "nueva zelanda": "🇳🇿",
    "países bajos": "🇳🇱",
    "paises bajos": "🇳🇱",
    "paraguay": "🇵🇾",
    "portugal": "🇵🇹",
    "qatar": "🇶🇦",
    "republica checa": "🇨🇿",
    "república checa": "🇨🇿",
    "sudafrica": "🇿🇦",
    "sudáfrica": "🇿🇦",
    "suecia": "🇸🇪",
    "suiza": "🇨🇭",
    "tunez": "🇹🇳",
    "túnez": "🇹🇳",
    "turquia": "🇹🇷",
    "turquía": "🇹🇷",
    "uruguay": "🇺🇾",
}

TEAM_COUNTRY_CODES = {
    "alemania": "DE",
    "arabia saudita": "SA",
    "argentina": "AR",
    "argelia": "DZ",
    "australia": "AU",
    "austria": "AT",
    "belgica": "BE",
    "bosnia herzegovina": "BA",
    "brasil": "BR",
    "cabo verde": "CV",
    "canada": "CA",
    "chile": "CL",
    "colombia": "CO",
    "corea del sur": "KR",
    "costa de marfil": "CI",
    "costa rica": "CR",
    "croacia": "HR",
    "curazao": "CW",
    "ecuador": "EC",
    "egipto": "EG",
    "escocia": "GB-SCT",
    "espana": "ES",
    "estados unidos": "US",
    "francia": "FR",
    "ghana": "GH",
    "haiti": "HT",
    "inglaterra": "GB",
    "irak": "IQ",
    "iran": "IR",
    "italia": "IT",
    "japon": "JP",
    "jordania": "JO",
    "marruecos": "MA",
    "mexico": "MX",
    "noruega": "NO",
    "nueva zelanda": "NZ",
    "panama": "PA",
    "paises bajos": "NL",
    "paraguay": "PY",
    "portugal": "PT",
    "qatar": "QA",
    "rd congo": "CD",
    "republica checa": "CZ",
    "senegal": "SN",
    "sudafrica": "ZA",
    "suecia": "SE",
    "suiza": "CH",
    "tunez": "TN",
    "turquia": "TR",
    "uruguay": "UY",
    "uzbekistan": "UZ",
}

TEAM_DISPLAY_NAMES = {
    "alemania": "Alemania",
    "arabia saudita": "Arabia Saudita",
    "argentina": "Argentina",
    "argelia": "Argelia",
    "australia": "Australia",
    "austria": "Austria",
    "belgica": "Bélgica",
    "bosnia herzegovina": "Bosnia Herzegovina",
    "brasil": "Brasil",
    "cabo verde": "Cabo Verde",
    "canada": "Canadá",
    "chile": "Chile",
    "colombia": "Colombia",
    "corea del sur": "Corea del Sur",
    "costa de marfil": "Costa de Marfil",
    "costa rica": "Costa Rica",
    "croacia": "Croacia",
    "curazao": "Curazao",
    "ecuador": "Ecuador",
    "egipto": "Egipto",
    "escocia": "Escocia",
    "espana": "España",
    "estados unidos": "Estados Unidos",
    "francia": "Francia",
    "ghana": "Ghana",
    "haiti": "Haití",
    "inglaterra": "Inglaterra",
    "irak": "Irak",
    "iran": "Irán",
    "italia": "Italia",
    "japon": "Japón",
    "jordania": "Jordania",
    "marruecos": "Marruecos",
    "mexico": "México",
    "noruega": "Noruega",
    "nueva zelanda": "Nueva Zelanda",
    "panama": "Panamá",
    "paises bajos": "Países Bajos",
    "paraguay": "Paraguay",
    "portugal": "Portugal",
    "qatar": "Qatar",
    "rd congo": "RD Congo",
    "republica checa": "República Checa",
    "senegal": "Senegal",
    "sudafrica": "Sudáfrica",
    "suecia": "Suecia",
    "suiza": "Suiza",
    "tunez": "Túnez",
    "turquia": "Turquía",
    "uruguay": "Uruguay",
    "uzbekistan": "Uzbekistán",
}

BRACKET_TEAM_OPTIONS = sorted({team for _stage, _starts_at, home, away in BRACKET_PLACEHOLDER_GAMES for team in (home, away)})


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=SECRET_KEY,
        PERMANENT_SESSION_LIFETIME=timedelta(days=60),
        SESSION_REFRESH_EACH_REQUEST=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("PRODE_COOKIE_SECURE", "0") == "1",
    )

    @app.before_request
    def load_user() -> None:
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        g.db = get_db()
        ensure_runtime_schema_once(g.db)
        g.database_path = current_database_path()
        g.database_name = current_database_name()
        g.is_primary_database = is_primary_database()
        g.user = None
        user_id = session.get("user_id")
        if user_id:
            session.permanent = True
            g.user = query_one("select * from users where id = ?", (user_id,))
        if g.user and request.endpoint not in PUBLIC_USER_ENDPOINTS:
            if g.user["force_password_change"]:
                return redirect(url_for("change_password"))
            if not accepted_current_terms(g.user):
                return redirect(url_for("legal_info"))

    @app.before_request
    def protect_posts() -> None:
        if request.method != "POST":
            return
        token = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
        if not token or not secrets.compare_digest(token, session.get("csrf_token", "")):
            session["csrf_token"] = secrets.token_urlsafe(32)
            if request.endpoint == "login":
                return
            if wants_json():
                return jsonify({"ok": False, "message": "Sesion vencida. Actualiza la pagina e intenta de nuevo."}), 400
            flash("Sesion vencida. Volve a intentar desde la pantalla actualizada.", "error")
            return redirect(url_for("index"))

    @app.teardown_appcontext
    def close_db(_error: Exception | None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.template_filter("money")
    def money(value: object) -> str:
        try:
            amount = float(value or 0)
        except (TypeError, ValueError):
            amount = 0
        return f"${amount:,.0f}".replace(",", ".")

    @app.route("/")
    def index():
        requested_db = request.args.get("db", "").strip()
        if requested_db and database_path_for_name(requested_db).exists():
            session["database_name"] = safe_database_name(requested_db) if requested_db != "principal" else "principal"
            return redirect(url_for("index"))
        if g.user:
            return redirect(url_for("dashboard"))
        return render_template("login.html", current_database=current_database_name())

    @app.route("/login", methods=["POST"])
    def login():
        requested_db = request.form.get("database_name", current_database_name())
        if database_path_for_name(requested_db).exists():
            session["database_name"] = safe_database_name(requested_db) if requested_db != "principal" else "principal"
            g.db.close()
            g.pop("db", None)
            g.db = get_db()
            g.database_name = current_database_name()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "").strip()
        if rate_limited(f"login:{client_ip()}:{username}", limit=8, window_seconds=300):
            flash("Demasiados intentos. Espera unos minutos y proba de nuevo.", "error")
            return redirect(url_for("index"))
        user = query_one("select * from users where username = ?", (username,))
        if not user or not check_password_hash(user["password_hash"], password):
            log_event("login_failed", f"Usuario: {username or '(vacio)'}")
            g.db.commit()
            flash("Usuario o clave incorrectos.", "error")
            return redirect(url_for("index"))
        if user["is_banned"]:
            log_event("login_banned", f"Usuario suspendido: {username}", user["id"])
            g.db.commit()
            flash("Tu cuenta esta suspendida para participar.", "error")
            return redirect(url_for("index"))
        database_name = current_database_name()
        session.clear()
        session.permanent = True
        session["csrf_token"] = secrets.token_urlsafe(32)
        if database_name:
            session["database_name"] = database_name
        session["user_id"] = user["id"]
        log_event("login", "Ingreso correcto", user["id"])
        g.db.commit()
        return redirect(url_for("dashboard"))

    @app.route("/cambiar-clave", methods=["GET", "POST"])
    @login_required
    def change_password():
        if request.method == "POST":
            password = request.form.get("password", "").strip()
            confirm = request.form.get("confirm", "").strip()
            if len(password) < 6:
                flash("La clave debe tener al menos 6 caracteres.", "error")
                return redirect(url_for("change_password"))
            if password != confirm:
                flash("Las claves no coinciden.", "error")
                return redirect(url_for("change_password"))
            g.db.execute(
                "update users set password_hash = ?, force_password_change = 0 where id = ?",
                (generate_password_hash(password), g.user["id"]),
            )
            log_event("password_change", "Cambio de clave propio")
            g.db.commit()
            flash("Clave actualizada.", "ok")
            return redirect(url_for("dashboard"))
        return render_template("change_password.html")

    @app.route("/informacion")
    @login_required
    def legal_info():
        settings = get_settings()
        legal_text = settings.get("legal_text", DEFAULT_LEGAL_TEXT)
        paragraphs = [block.strip() for block in legal_text.splitlines() if block.strip()]
        return render_template(
            "legal.html",
            legal_paragraphs=paragraphs,
            legal_updated_at=settings.get("legal_updated_at"),
            accepted_current=accepted_current_terms(g.user),
        )

    @app.route("/informacion/aceptar", methods=["POST"])
    @login_required
    def legal_accept():
        decision = request.form.get("decision")
        if decision != "accept":
            database_name = session.get("database_name")
            session.clear()
            if database_name:
                session["database_name"] = database_name
            flash("No se aceptaron las condiciones.", "error")
            return redirect(url_for("index"))
        g.db.execute("update users set accepted_terms_at = ? where id = ?", (utc_now(), g.user["id"]))
        log_event("legal_accept", "Acepto informacion legal vigente")
        g.db.commit()
        flash("Condiciones aceptadas.", "ok")
        return redirect(url_for("dashboard"))

    @app.route("/logout")
    def logout():
        database_name = session.get("database_name")
        session.clear()
        if database_name:
            session["database_name"] = database_name
        return redirect(url_for("index"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        stages = get_stages()
        active_stage_index = next((index for index, stage in enumerate(stages) if not stage["is_locked"]), 0)
        active_stage = stages[active_stage_index]
        playing_stage = stages[active_stage_index - 1] if active_stage_index > 0 else active_stage
        games = query_all(
            "select * from games where stage_key = ? order by starts_at, id",
            (active_stage["stage_key"],),
        )
        predictions = {
            row["game_id"]: row
            for row in query_all("select * from predictions where user_id = ?", (g.user["id"],))
        }
        return render_template(
            "dashboard.html",
            stages=stages,
            active_stage=active_stage,
            games=games,
            predictions=predictions,
            settings=get_settings(),
            leaderboard=leaderboard(),
            playing_stage=playing_stage,
            playing_stage_board=leaderboard(playing_stage["stage_key"]),
            prediction_progress=prediction_progress(g.user["id"]),
            stage_winners=stage_winners(),
            prize_rows=prize_rows(),
        )

    @app.route("/fixture")
    @login_required
    def fixture():
        stages = get_stages()
        games_by_stage = {
            stage["stage_key"]: query_all(
                "select * from games where stage_key = ? order by starts_at, id",
                (stage["stage_key"],),
            )
            for stage in stages
        }
        first_open_index = next((index for index, stage in enumerate(stages) if not stage["is_locked"]), None)
        first_open_stage_key = None
        current_playing_stage_key = None
        if first_open_index is None:
            for stage in reversed(stages):
                if not stage_locked_and_played(stage, games_by_stage[stage["stage_key"]]):
                    current_playing_stage_key = stage["stage_key"]
                    break
        else:
            first_open_stage_key = stages[first_open_index]["stage_key"]
            if first_open_index > 0:
                previous_stage = stages[first_open_index - 1]
                if not stage_locked_and_played(previous_stage, games_by_stage[previous_stage["stage_key"]]):
                    current_playing_stage_key = previous_stage["stage_key"]
        default_fixture_stage_key = current_playing_stage_key or first_open_stage_key
        locked_played_stage_keys = {
            stage["stage_key"]
            for stage in stages
            if stage_locked_and_played(stage, games_by_stage[stage["stage_key"]])
        }
        if default_fixture_stage_key in locked_played_stage_keys:
            default_fixture_stage_key = first_open_stage_key if first_open_stage_key not in locked_played_stage_keys else None
        fixture_states = {}
        fixture_state_summaries = {}
        now = datetime.now(APP_TIMEZONE)
        for stage in stages:
            stage_key = stage["stage_key"]
            stage_states, stage_summary = fixture_game_states(
                games_by_stage[stage_key],
                now,
                mark_next=stage_key == current_playing_stage_key,
            )
            fixture_states[stage_key] = stage_states
            fixture_state_summaries[stage_key] = stage_summary
        predictions = {
            row["game_id"]: row
            for row in query_all("select * from predictions where user_id = ?", (g.user["id"],))
        }
        return render_template(
            "fixture.html",
            stages=stages,
            games_by_stage=games_by_stage,
            first_open_stage_key=first_open_stage_key,
            current_playing_stage_key=current_playing_stage_key,
            default_fixture_stage_key=default_fixture_stage_key,
            locked_played_stage_keys=locked_played_stage_keys,
            fixture_states=fixture_states,
            fixture_state_summaries=fixture_state_summaries,
            predictions=predictions,
        )

    @app.route("/predict/<int:game_id>", methods=["POST"])
    @login_required
    def predict(game_id: int):
        game = query_one("select * from games where id = ?", (game_id,))
        if not game:
            abort(404)
        try:
            home_goals = int(request.form.get("home_goals", ""))
            away_goals = int(request.form.get("away_goals", ""))
        except ValueError:
            return prediction_error("Los goles tienen que ser numeros.")
        penalty_winner = clean_side_choice(request.form.get("penalty_winner"))
        error = save_prediction(game, home_goals, away_goals, penalty_winner)
        if error:
            return prediction_error(error)
        g.db.commit()
        if wants_json():
            return jsonify(
                {
                    "ok": True,
                    "message": "Prediccion guardada.",
                    "game_id": game_id,
                    "label": prediction_text(game, home_goals, away_goals, penalty_winner),
                }
            )
        flash("Prediccion guardada.", "ok")
        return redirect(url_for("dashboard"))

    @app.route("/predictions/batch", methods=["POST"])
    @login_required
    def predict_batch():
        saved = 0
        errors = []
        saved_predictions = {}
        game_ids = request.form.getlist("game_id")
        for raw_game_id in game_ids:
            try:
                game_id = int(raw_game_id)
                home_goals = int(request.form.get(f"home_goals_{game_id}", ""))
                away_goals = int(request.form.get(f"away_goals_{game_id}", ""))
                penalty_winner = clean_side_choice(request.form.get(f"penalty_winner_{game_id}"))
            except ValueError:
                errors.append("Hay goles con formato invalido.")
                continue
            game = query_one("select * from games where id = ?", (game_id,))
            if not game:
                errors.append(f"Partido {game_id} no existe.")
                continue
            error = save_prediction(game, home_goals, away_goals, penalty_winner)
            if error:
                errors.append(error)
                continue
            saved += 1
            saved_predictions[game_id] = prediction_text(game, home_goals, away_goals, penalty_winner)
        if saved:
            g.db.commit()
        message = f"{saved} predicciones guardadas." if saved != 1 else "1 prediccion guardada."
        if wants_json():
            return jsonify({"ok": not errors, "saved": saved, "message": message, "errors": errors, "predictions": saved_predictions}), (400 if errors and not saved else 200)
        flash(message, "ok" if saved else "error")
        for error in errors[:3]:
            flash(error, "error")
        return redirect(url_for("dashboard"))

    @app.route("/standings")
    @login_required
    def standings():
        return render_template(
            "standings.html",
            rows=leaderboard(),
            stage_rows=stage_leaderboards(),
            stage_winners=stage_winners(),
            prize_rows=prize_rows(),
            settings=get_settings(),
        )

    @app.route("/historico")
    @login_required
    def history():
        history_data = historical_progress()
        return render_template(
            "history.html",
            history_groups=history_data["groups"],
            history_chart=history_data["chart"],
            history_stage_chart=history_data["stage_chart"],
            latest_history_event=history_data["latest_event"],
        )

    @app.route("/chat")
    @login_required
    def chat():
        touch_chat_presence()
        active_timeout = current_chat_timeout()
        return render_template("chat.html", active_timeout=active_timeout)

    @app.route("/chat/messages")
    @login_required
    def chat_messages():
        touch_chat_presence()
        after_id = request.args.get("after_id", "0")
        try:
            after_id_int = int(after_id)
        except ValueError:
            after_id_int = 0
        visible_after_id = int(get_settings().get("chat_visible_after_id", "0") or 0)
        after_id_int = max(after_id_int, visible_after_id)
        messages = query_all(
            """
            select * from (
                select chat_messages.*, users.display_name, users.username, users.is_banned
                from chat_messages join users on users.id = chat_messages.user_id
                where chat_messages.id > ?
                order by chat_messages.id desc limit 100
            ) order by id asc
            """,
            (after_id_int,),
        )
        return jsonify(
            {
                "messages": [chat_message_payload(message) for message in messages],
                "is_admin": bool(g.user["is_admin"]),
                "visible_after_id": visible_after_id,
            }
        )

    @app.route("/chat/users")
    @login_required
    def chat_users():
        touch_chat_presence()
        users = query_all(
            """
            select id, display_name, username, is_admin, is_banned, chat_seen_at
            from users
            where chat_seen_at is not null and chat_seen_at > ?
            order by is_admin desc, username
            """,
            (chat_presence_cutoff(),),
        )
        return jsonify({"users": [chat_user_payload(user) for user in users]})

    @app.route("/chat/send", methods=["POST"])
    @login_required
    def chat_send():
        touch_chat_presence()
        active_timeout = current_chat_timeout()
        if active_timeout:
            return jsonify({"ok": False, "error": "Tenes un timeout activo para escribir en el chat."}), 403
        if rate_limited(f"chat:{g.user['id']}", limit=12, window_seconds=20):
            return jsonify({"ok": False, "error": "Estas enviando mensajes muy rapido. Espera unos segundos."}), 429
        body = request.form.get("body", "").strip()
        if not body:
            return jsonify({"ok": False, "error": "El mensaje esta vacio."}), 400
        cursor = g.db.execute(
            "insert into chat_messages (user_id, body, created_at, is_deleted) values (?, ?, ?, 0)",
            (g.user["id"], body[:800], utc_now()),
        )
        g.db.commit()
        message = query_one(
            """
            select chat_messages.*, users.display_name, users.username, users.is_banned
            from chat_messages join users on users.id = chat_messages.user_id
            where chat_messages.id = ?
            """,
            (cursor.lastrowid,),
        )
        return jsonify({"ok": True, "message": chat_message_payload(message)})

    @app.route("/chat/<int:message_id>/delete", methods=["POST"])
    @admin_required
    def chat_delete_json(message_id: int):
        g.db.execute("update chat_messages set is_deleted = 1 where id = ?", (message_id,))
        log_event("chat_delete", f"Mensaje {message_id} moderado")
        g.db.commit()
        return jsonify({"ok": True, "id": message_id})

    @app.route("/chat/users/<int:user_id>/timeout", methods=["POST"])
    @admin_required
    def chat_timeout_json(user_id: int):
        minutes = max(1, int(request.form.get("minutes", 15)))
        reason = request.form.get("reason", "").strip() or "Timeout desde chat"
        expires_at = datetime.fromtimestamp(datetime.now().timestamp() + minutes * 60, timezone.utc).isoformat()
        g.db.execute(
            "insert into sanctions (user_id, admin_id, type, reason, expires_at, created_at) values (?, ?, 'timeout', ?, ?, ?)",
            (user_id, g.user["id"], reason, expires_at, utc_now()),
        )
        log_event("chat_timeout", f"Timeout desde chat: {minutes} min. {reason}", user_id)
        g.db.commit()
        return jsonify({"ok": True})

    @app.route("/chat/users/<int:user_id>/ban", methods=["POST"])
    @admin_required
    def chat_ban_json(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user or user["id"] == g.user["id"]:
            abort(404)
        reason = request.form.get("reason", "").strip() or "Baneado desde chat"
        g.db.execute("update users set is_banned = 1 where id = ?", (user_id,))
        g.db.execute(
            "insert into sanctions (user_id, admin_id, type, reason, created_at) values (?, ?, 'ban', ?, ?)",
            (user_id, g.user["id"], reason, utc_now()),
        )
        log_event("chat_ban", f"Ban desde chat: {reason}", user_id)
        g.db.commit()
        return jsonify({"ok": True})

    @app.route("/chat/clear", methods=["POST"])
    @admin_required
    def chat_clear_json():
        latest = query_one("select coalesce(max(id), 0) as id from chat_messages")["id"]
        reason = request.form.get("reason", "").strip() or "Sala limpiada por admin"
        g.db.execute(
            "insert into settings (key, value) values ('chat_visible_after_id', ?) on conflict(key) do update set value = excluded.value",
            (str(latest),),
        )
        g.db.execute(
            "insert into sanctions (user_id, admin_id, type, reason, created_at) values (?, ?, 'chat_clear', ?, ?)",
            (g.user["id"], g.user["id"], reason, utc_now()),
        )
        log_event("chat_clear", reason)
        g.db.commit()
        return jsonify({"ok": True, "visible_after_id": latest})

    def current_chat_timeout():
        active_timeout = query_one(
            """
            select * from sanctions
            where user_id = ? and type = 'timeout' and (expires_at is null or expires_at > ?)
            order by id desc limit 1
            """,
            (g.user["id"], utc_now()),
        )
        return active_timeout

    @app.route("/admin")
    @admin_required
    def admin():
        stages = get_stages()
        users = query_all("select * from users order by is_admin desc, username")
        user_prediction_audit = admin_prediction_audit(users, stages)
        prediction_audit_summary = next(
            iter(user_prediction_audit.values()),
            {"total": 0, "tournament_total": 0, "future_total": 0},
        )
        current_stage_key = current_results_stage_key(stages)
        selected_stage_key = request.args.get("results_stage") or current_stage_key
        valid_stage_keys = {stage["stage_key"] for stage in stages}
        if selected_stage_key != "all" and selected_stage_key not in valid_stage_keys:
            selected_stage_key = current_stage_key
        result_games = query_all("select * from games order by starts_at, id")
        return render_template(
            "admin.html",
            users=users,
            user_prediction_audit=user_prediction_audit,
            prediction_audit_summary=prediction_audit_summary,
            audit_groups=audit_groups(),
            stages=stages,
            games=result_games,
            selected_results_stage_key=selected_stage_key,
            current_results_stage_key=current_stage_key,
            settings=get_settings(),
            can_debug=can_debug(),
            databases=available_databases(),
            current_database=current_database_name(),
            is_primary_database=is_primary_database(),
            backup_status=backup_status(),
            sanctions=query_all(
                """
                select sanctions.*, users.username
                from sanctions join users on users.id = sanctions.user_id
                order by sanctions.id desc limit 30
                """
            ),
        )

    @app.route("/admin/ranking-image")
    @admin_required
    def admin_ranking_image():
        now = datetime.now(APP_TIMEZONE)
        return render_template(
            "admin_ranking_image.html",
            ranking_payload=ranking_image_payload(),
            default_title=f"La Fija Mundialera - Tablas y premios ({now.strftime('%d/%m/%y')})",
        )

    @app.route("/admin/backup/json", methods=["POST"])
    @admin_required
    def admin_backup_json():
        path = create_backup("full")
        log_event("admin_backup_json", f"Backup JSON descargado: {path.name}")
        g.db.commit()
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.route("/admin/backup/sqlite", methods=["POST"])
    @admin_required
    def admin_backup_sqlite():
        g.db.commit()
        path = create_sqlite_backup()
        log_event("admin_backup_sqlite", f"Backup SQLite descargado: {path.name}")
        g.db.commit()
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.route("/admin/backup/restore", methods=["POST"])
    @admin_required
    def admin_restore_backup():
        confirmation = request.form.get("confirmation", "").strip().upper()
        uploaded = request.files.get("backup_file")
        if confirmation != "RESTAURAR":
            flash("Para restaurar escribi RESTAURAR.", "error")
            return redirect(url_for("admin"))
        if not uploaded or not uploaded.filename:
            flash("Selecciona un archivo de backup SQLite.", "error")
            return redirect(url_for("admin"))
        if not uploaded.filename.lower().endswith((".sqlite3", ".db", ".sqlite")):
            flash("Solo se puede restaurar un backup SQLite.", "error")
            return redirect(url_for("admin"))
        try:
            before_path = create_sqlite_backup(prefix="pre-restore")
            restore_sqlite_backup(uploaded)
            get_db()
            log_event("admin_backup_restore", f"Restauro backup {uploaded.filename}; previo guardado en {before_path.name}")
            g.db.commit()
            flash("Backup restaurado. Se guardo una copia previa por seguridad.", "ok")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("admin"))

    @app.route("/admin/users", methods=["POST"])
    @admin_required
    def admin_create_user():
        username = request.form.get("username", "").strip().lower()
        display_name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "").strip()
        is_admin = 1 if request.form.get("is_admin") == "on" else 0
        is_debugger = 1 if request.form.get("is_debugger") == "on" else 0
        force_password_change = 1 if request.form.get("force_password_change") == "on" else 0
        if not username or not display_name or not password:
            flash("Completá usuario, nombre y clave.", "error")
            return redirect(url_for("admin"))
        try:
            g.db.execute(
                """
                insert into users (username, display_name, password_hash, is_admin, is_debugger, force_password_change, is_banned, created_at)
                values (?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (username, display_name, generate_password_hash(password), is_admin, is_debugger, force_password_change, utc_now()),
            )
            log_event("admin_user_create", f"Creo usuario @{username}")
            g.db.commit()
            flash("Usuario creado.", "ok")
        except sqlite3.IntegrityError:
            flash("Ese usuario ya existe.", "error")
        return redirect(url_for("admin"))

    @app.route("/admin/users/<int:user_id>/toggle-ban", methods=["POST"])
    @admin_required
    def admin_toggle_ban(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user or user["id"] == g.user["id"]:
            abort(404)
        new_state = 0 if user["is_banned"] else 1
        reason = request.form.get("reason", "").strip() or ("Ban levantado" if not new_state else "Baneado por admin")
        g.db.execute("update users set is_banned = ? where id = ?", (new_state, user_id))
        g.db.execute(
            "insert into sanctions (user_id, admin_id, type, reason, created_at) values (?, ?, ?, ?, ?)",
            (user_id, g.user["id"], "ban" if new_state else "unban", reason, utc_now()),
        )
        log_event("admin_ban_toggle", f"{'Baneo' if new_state else 'Levanto ban'} @{user['username']}: {reason}", user_id)
        g.db.commit()
        flash("Estado actualizado.", "ok")
        return redirect(url_for("admin"))

    @app.route("/admin/users/<int:user_id>/update", methods=["POST"])
    @admin_required
    def admin_update_user(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            abort(404)
        username = request.form.get("username", "").strip().lower()
        display_name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "user")
        is_admin = 1 if role == "admin" else 0
        is_debugger = 1 if request.form.get("is_debugger") == "on" else 0
        is_banned = 1 if request.form.get("is_banned") == "on" else 0
        force_password_change = 1 if request.form.get("force_password_change") == "on" else 0
        if not username or not display_name:
            flash("Completá usuario y nombre.", "error")
            return redirect(url_for("admin"))
        if user_id == g.user["id"] and not is_admin:
            flash("No podés quitarte tu propio rol admin.", "error")
            return redirect(url_for("admin"))
        if user["is_admin"] and not is_admin and admin_count() <= 1:
            flash("Tiene que quedar al menos un admin.", "error")
            return redirect(url_for("admin"))
        try:
            if password.strip():
                g.db.execute(
                    """
                    update users
                    set username = ?, display_name = ?, password_hash = ?, is_admin = ?, is_debugger = ?, is_banned = ?, force_password_change = ?
                    where id = ?
                    """,
                    (username, display_name, generate_password_hash(password), is_admin, is_debugger, is_banned, force_password_change, user_id),
                )
            else:
                g.db.execute(
                    """
                    update users
                    set username = ?, display_name = ?, is_admin = ?, is_debugger = ?, is_banned = ?, force_password_change = ?
                    where id = ?
                    """,
                    (username, display_name, is_admin, is_debugger, is_banned, force_password_change, user_id),
                )
            g.db.commit()
            log_event("admin_user_update", f"Actualizo usuario @{username}", user_id)
            g.db.commit()
            flash("Usuario actualizado.", "ok")
        except sqlite3.IntegrityError:
            flash("Ese usuario ya existe.", "error")
        return redirect(url_for("admin"))

    @app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
    @admin_required
    def admin_delete_user(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            abort(404)
        if user_id == g.user["id"]:
            flash("No podés eliminar tu propio usuario.", "error")
            return redirect(url_for("admin"))
        if user["is_admin"] and admin_count() <= 1:
            flash("Tiene que quedar al menos un admin.", "error")
            return redirect(url_for("admin"))
        g.db.execute("delete from predictions where user_id = ?", (user_id,))
        g.db.execute("delete from chat_messages where user_id = ?", (user_id,))
        g.db.execute("delete from sanctions where user_id = ? or admin_id = ?", (user_id, user_id))
        g.db.execute("delete from users where id = ?", (user_id,))
        log_event("admin_user_delete", f"Elimino usuario @{user['username']}", user_id)
        g.db.commit()
        flash("Usuario eliminado.", "ok")
        return redirect(url_for("admin"))

    @app.route("/admin/users/<int:user_id>/timeout", methods=["POST"])
    @admin_required
    def admin_timeout(user_id: int):
        minutes = max(1, int(request.form.get("minutes", 15)))
        reason = request.form.get("reason", "").strip() or "Timeout de chat"
        expires_at = datetime.fromtimestamp(datetime.now().timestamp() + minutes * 60, timezone.utc).isoformat()
        g.db.execute(
            "insert into sanctions (user_id, admin_id, type, reason, expires_at, created_at) values (?, ?, 'timeout', ?, ?, ?)",
            (user_id, g.user["id"], reason, expires_at, utc_now()),
        )
        log_event("admin_timeout", f"Timeout a @{user_id}: {minutes} min. {reason}", user_id)
        g.db.commit()
        flash("Timeout aplicado.", "ok")
        return redirect(url_for("admin"))

    @app.route("/admin/users/<int:user_id>/toggle-debugger", methods=["POST"])
    @admin_required
    def admin_toggle_debugger(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            abort(404)
        new_state = 0 if user["is_debugger"] else 1
        g.db.execute("update users set is_debugger = ? where id = ?", (new_state, user_id))
        log_event("admin_debug_toggle", f"{'Dio debug' if new_state else 'Quito debug'} @{user['username']}", user_id)
        g.db.commit()
        flash("Rol debugger actualizado.", "ok")
        return redirect(url_for("admin"))

    @app.route("/admin/stages/<stage_key>/toggle", methods=["POST"])
    @admin_required
    def admin_toggle_stage(stage_key: str):
        stage = query_one("select * from stages where stage_key = ?", (stage_key,))
        if not stage:
            abort(404)
        g.db.execute("update stages set is_locked = ? where stage_key = ?", (0 if stage["is_locked"] else 1, stage_key))
        log_event("admin_stage_toggle", f"{stage['label']}: {'abrio' if stage['is_locked'] else 'bloqueo'}")
        g.db.commit()
        flash("Etapa actualizada.", "ok")
        return redirect(url_for("admin"))

    @app.route("/admin/stages/<stage_key>/activate-only", methods=["POST"])
    @admin_required
    def admin_activate_only_stage(stage_key: str):
        stage = query_one("select * from stages where stage_key = ?", (stage_key,))
        if not stage:
            abort(404)
        g.db.execute("update stages set is_locked = 1")
        g.db.execute("update stages set is_locked = 0 where stage_key = ?", (stage_key,))
        log_event("admin_stage_activate", f"Activo solo {stage['label']}")
        g.db.commit()
        flash(f"{stage['label']} activa; el resto quedo bloqueado.", "ok")
        return redirect(url_for("admin"))

    @app.route("/admin/games/<int:game_id>", methods=["POST"])
    @admin_required
    def admin_update_game(game_id: int):
        game = query_one("select * from games where id = ?", (game_id,))
        if not game:
            abort(404)
        starts_at = request.form.get("starts_at", game["starts_at"]).strip()
        home_team = request.form.get("home_team", game["home_team"]).strip()
        away_team = request.form.get("away_team", game["away_team"]).strip()
        if not starts_at or not home_team or not away_team:
            flash("Completá horario, local y visitante para guardar el partido.", "error")
            return redirect(admin_results_url())
        fixture_changed = starts_at != game["starts_at"] or home_team != game["home_team"] or away_team != game["away_team"]
        fixture_manual = 1 if fixture_changed or request.form.get("fixture_manual") == "1" else 0
        home_score = blank_to_none(request.form.get("home_score"))
        away_score = blank_to_none(request.form.get("away_score"))
        penalty_winner = clean_side_choice(request.form.get("result_penalty_winner"))
        if needs_penalty_winner(game["stage_key"], home_score, away_score) and not penalty_winner:
            flash("Elegi quien clasifica por penales para guardar ese empate.", "error")
            return redirect(admin_results_url())
        stored_penalty_winner = penalty_winner_for_result(game["stage_key"], home_score, away_score, penalty_winner)
        result = result_from_score_and_penalties(game["stage_key"], home_score, away_score, stored_penalty_winner)
        result_status = "manual" if result is not None else "pending"
        g.db.execute(
            """
            update games
            set starts_at = ?, home_team = ?, away_team = ?,
                home_score = ?, away_score = ?, result = ?, result_penalty_winner = ?, result_status = ?,
                fixture_manual = ?
            where id = ?
            """,
            (starts_at, home_team, away_team, home_score, away_score, result, stored_penalty_winner, result_status, fixture_manual, game_id),
        )
        penalty_label = home_team if stored_penalty_winner == "home" else away_team if stored_penalty_winner == "away" else ""
        detail = f"{penalty_label} por penales" if stored_penalty_winner else (result or "sin resultado")
        fixture_detail = f"; fixture manual: {home_team} vs {away_team} {starts_at}" if fixture_changed else ""
        log_event("admin_result_update", f"Partido {game_id}: {home_score}-{away_score} ({detail}){fixture_detail}")
        g.db.commit()
        flash("Resultado guardado.", "ok")
        return redirect(admin_results_url())

    @app.route("/admin/games/<int:game_id>/clear-result", methods=["POST"])
    @admin_required
    def admin_clear_game_result(game_id: int):
        game = query_one("select * from games where id = ?", (game_id,))
        if not game:
            abort(404)
        g.db.execute(
            "update games set home_score = null, away_score = null, result = null, result_penalty_winner = null, result_status = 'pending' where id = ?",
            (game_id,),
        )
        log_event("admin_result_clear", f"Partido {game_id}: {game['home_team']} vs {game['away_team']} quedo sin resultado")
        g.db.commit()
        flash("Resultado borrado.", "ok")
        return redirect(admin_results_url())

    @app.route("/admin/games", methods=["POST"])
    @admin_required
    def admin_create_game():
        stage_key = request.form.get("stage_key")
        starts_at = request.form.get("starts_at", "").strip()
        home_team = request.form.get("home_team", "").strip()
        away_team = request.form.get("away_team", "").strip()
        if not query_one("select 1 from stages where stage_key = ?", (stage_key,)):
            abort(400)
        if not starts_at or not home_team or not away_team:
            flash("Completá etapa, fecha y equipos.", "error")
            return redirect(url_for("admin"))
        g.db.execute(
            "insert into games (stage_key, starts_at, home_team, away_team) values (?, ?, ?, ?)",
            (stage_key, starts_at, home_team, away_team),
        )
        log_event("admin_game_create", f"{home_team} vs {away_team} ({stage_key})")
        g.db.commit()
        flash("Partido agregado.", "ok")
        return redirect(url_for("admin"))

    @app.route("/admin/settings", methods=["POST"])
    @admin_required
    def admin_settings():
        for key in SETTINGS_DEFAULTS:
            if key in {"legal_text", "legal_updated_at"}:
                continue
            if key not in request.form:
                continue
            values = request.form.getlist(key)
            value = (values[-1] if values else SETTINGS_DEFAULTS[key]).strip()
            g.db.execute(
                "insert into settings (key, value) values (?, ?) on conflict(key) do update set value = excluded.value",
                (key, value),
            )
        g.db.commit()
        log_event("admin_settings_update", "Actualizo premios/API")
        g.db.commit()
        flash("Configuracion guardada.", "ok")
        return redirect(url_for("admin"))

    @app.route("/admin/legal", methods=["POST"])
    @admin_required
    def admin_legal():
        legal_text = request.form.get("legal_text", "").strip()
        if not legal_text:
            flash("El texto de informacion no puede quedar vacio.", "error")
            return redirect(url_for("admin"))
        now = utc_now()
        for key, value in {"legal_text": legal_text, "legal_updated_at": now}.items():
            g.db.execute(
                "insert into settings (key, value) values (?, ?) on conflict(key) do update set value = excluded.value",
                (key, value),
            )
        log_event("admin_legal_update", "Actualizo informacion legal")
        g.db.commit()
        flash("Informacion legal actualizada. Los usuarios deberan aceptar la nueva version.", "ok")
        return redirect(url_for("admin"))

    @app.route("/admin/sync-promiedos", methods=["POST"])
    @admin_required
    def admin_sync_promiedos():
        try:
            stats = sync_promiedos_fixture()
        except Exception as exc:
            flash(f"No se pudo sincronizar Promiedos: {exc}", "error")
            return redirect(url_for("admin"))
        flash(
            f"Promiedos sincronizado: {stats['created']} nuevos, {stats['updated']} actualizados, {stats['skipped']} omitidos.",
            "ok",
        )
        return redirect(url_for("admin"))

    @app.route("/admin/auto-results/run-once", methods=["POST"])
    @admin_required
    def admin_auto_results_run_once():
        try:
            stats = sync_auto_results_once(manual=True)
        except Exception as exc:
            flash(f"No se pudo ejecutar auto resultados: {exc}", "error")
            return redirect(url_for("admin"))
        flash(auto_results_flash_message(stats), "ok" if not stats["errors"] else "error")
        return redirect(url_for("admin"))

    @app.route("/admin/chat/<int:message_id>/delete", methods=["POST"])
    @admin_required
    def admin_delete_message(message_id: int):
        g.db.execute("update chat_messages set is_deleted = 1 where id = ?", (message_id,))
        g.db.commit()
        flash("Mensaje moderado.", "ok")
        return redirect(url_for("chat"))

    @app.route("/debug/fake-users", methods=["POST"])
    @debug_required
    def debug_fake_users():
        if is_primary_database():
            flash("No se pueden crear datos fake en la base principal. Cloná o seleccioná una sandbox.", "error")
            return redirect(url_for("admin"))
        count = min(max(int(request.form.get("count", 8)), 1), 50)
        created = seed_fake_users(count)
        flash(f"Usuarios fake creados: {created}.", "ok")
        return redirect(url_for("admin"))

    @app.route("/debug/fake-predictions", methods=["POST"])
    @debug_required
    def debug_fake_predictions():
        if is_primary_database():
            flash("No se pueden cargar predicciones fake en la base principal. Usá una sandbox.", "error")
            return redirect(url_for("admin"))
        stage_key = request.form.get("stage_key", "fecha_1")
        created = seed_fake_predictions(stage_key)
        flash(f"Predicciones fake cargadas: {created}.", "ok")
        return redirect(url_for("admin"))

    @app.route("/debug/fake-results", methods=["POST"])
    @debug_required
    def debug_fake_results():
        if is_primary_database():
            flash("No se pueden cargar resultados fake en la base principal. Usá una sandbox.", "error")
            return redirect(url_for("admin"))
        stage_key = request.form.get("stage_key", "fecha_1")
        updated = seed_fake_results(stage_key)
        flash(f"Resultados fake cargados: {updated}.", "ok")
        return redirect(url_for("admin"))

    @app.route("/debug/backup/<kind>", methods=["POST"])
    @debug_required
    def debug_backup(kind: str):
        stage_key = request.form.get("stage_key")
        path = create_backup(kind, stage_key)
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.route("/debug/databases/select", methods=["POST"])
    @debug_required
    def debug_select_database():
        name = request.form.get("database", "principal")
        if not database_path_for_name(name).exists():
            flash("Esa base no existe.", "error")
            return redirect(url_for("admin"))
        session["database_name"] = name
        session.pop("user_id", None)
        flash(f"Base seleccionada: {name}. Iniciá sesión nuevamente.", "ok")
        return redirect(url_for("index"))

    @app.route("/debug/databases/clone", methods=["POST"])
    @debug_required
    def debug_clone_database():
        raw_name = request.form.get("name", "").strip()
        name = safe_database_name(raw_name)
        if not name:
            flash("Indicá un nombre válido para la base sandbox.", "error")
            return redirect(url_for("admin"))
        target = database_path_for_name(name)
        if target.exists():
            flash("Ya existe una base con ese nombre.", "error")
            return redirect(url_for("admin"))
        DATABASE_DIR.mkdir(exist_ok=True)
        shutil.copy2(current_database_path(), target)
        flash(f"Sandbox creada: {name}.", "ok")
        return redirect(url_for("admin"))

    @app.context_processor
    def inject_globals():
        return {
            "stage_label": stage_label,
            "choice_label": choice_label,
            "prediction_label": prediction_label,
            "prediction_status": prediction_status,
            "prediction_status_label": prediction_status_label,
            "game_result": game_result,
            "game_is_final": game_is_final,
            "game_is_live": game_is_live,
            "game_penalty_winner": game_penalty_winner,
            "game_went_to_penalties": game_went_to_penalties,
            "result_detail_label": result_detail_label,
            "game_status_label": game_status_label,
            "is_knockout_stage": is_knockout_stage,
            "needs_penalty_winner": needs_penalty_winner,
            "team_label": team_label,
            "team_flag": team_flag,
            "team_select_options": team_select_options,
            "team_select_values": team_select_values,
            "bracket_team_options": bracket_team_options,
            "rank_badge": rank_badge,
            "asset_version": asset_version,
            "app_name": APP_NAME,
            "current_page_label": current_page_label,
            "accepted_current_terms": accepted_current_terms,
            "format_datetime": format_datetime,
            "format_game_datetime": format_game_datetime,
            "csrf_token": lambda: session.get("csrf_token", ""),
        }

    start_auto_results_worker(app)
    return app


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        current_database_path().parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(current_database_path(), timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("pragma busy_timeout = 15000")
        g.db.execute("pragma journal_mode = wal")
        g.db.execute("pragma synchronous = normal")
    return g.db


def ensure_runtime_schema_once(db: sqlite3.Connection) -> None:
    path = current_database_path().resolve()
    if path in SCHEMA_READY_PATHS:
        return
    with SCHEMA_READY_LOCK:
        if path in SCHEMA_READY_PATHS:
            return
        ensure_runtime_schema(db)
        db.commit()
        SCHEMA_READY_PATHS.add(path)


def forget_runtime_schema(path: Path | None = None) -> None:
    target = (path or current_database_path()).resolve()
    with SCHEMA_READY_LOCK:
        SCHEMA_READY_PATHS.discard(target)


def ensure_runtime_schema(db: sqlite3.Connection) -> None:
    if not table_exists(db, "users"):
        bootstrap_database(db)
        return
    ensure_column(db, "users", "last_seen_at", "text")
    ensure_column(db, "users", "is_debugger", "integer not null default 0")
    ensure_column(db, "users", "is_banned", "integer not null default 0")
    ensure_column(db, "users", "force_password_change", "integer not null default 0")
    ensure_column(db, "users", "accepted_terms_at", "text")
    ensure_column(db, "users", "chat_seen_at", "text")
    if table_exists(db, "games"):
        ensure_column(db, "games", "external_id", "text")
        ensure_column(db, "games", "result_status", "text not null default 'pending'")
        ensure_column(db, "games", "result_penalty_winner", "text")
        ensure_column(db, "games", "fixture_manual", "integer not null default 0")
        mark_existing_results_final(db)
    if table_exists(db, "predictions"):
        ensure_column(db, "predictions", "home_goals", "integer")
        ensure_column(db, "predictions", "away_goals", "integer")
        ensure_column(db, "predictions", "penalty_winner", "text")
    if table_exists(db, "settings"):
        ensure_settings_defaults(db)
    db.execute(
        """
        create table if not exists audit_logs (
            id integer primary key autoincrement,
            user_id integer,
            actor_id integer,
            action text not null,
            detail text,
            ip_address text,
            user_agent text,
            created_at text not null
        )
        """
    )
    ensure_indexes(db)


def bootstrap_database(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        create table if not exists users (
            id integer primary key autoincrement,
            username text not null unique,
            display_name text not null,
            password_hash text not null,
            is_admin integer not null default 0,
            is_debugger integer not null default 0,
            is_banned integer not null default 0,
            last_seen_at text,
            chat_seen_at text,
            force_password_change integer not null default 0,
            accepted_terms_at text,
            created_at text not null
        );
        create table if not exists stages (
            stage_key text primary key,
            label text not null,
            sort_order integer not null,
            is_bonus integer not null default 0,
            is_locked integer not null default 0
        );
        create table if not exists games (
            id integer primary key autoincrement,
            external_id text unique,
            stage_key text not null references stages(stage_key),
            starts_at text not null,
            home_team text not null,
            away_team text not null,
            home_score integer,
            away_score integer,
            result text,
            result_penalty_winner text,
            result_status text not null default 'pending',
            fixture_manual integer not null default 0
        );
        create table if not exists predictions (
            id integer primary key autoincrement,
            user_id integer not null references users(id),
            game_id integer not null references games(id),
            choice text not null,
            home_goals integer,
            away_goals integer,
            penalty_winner text,
            updated_at text not null,
            unique(user_id, game_id)
        );
        create table if not exists settings (
            key text primary key,
            value text not null
        );
        create table if not exists chat_messages (
            id integer primary key autoincrement,
            user_id integer not null references users(id),
            body text not null,
            created_at text not null,
            is_deleted integer not null default 0
        );
        create table if not exists sanctions (
            id integer primary key autoincrement,
            user_id integer not null references users(id),
            admin_id integer not null references users(id),
            type text not null,
            reason text not null,
            expires_at text,
            created_at text not null
        );
        create table if not exists audit_logs (
            id integer primary key autoincrement,
            user_id integer,
            actor_id integer,
            action text not null,
            detail text,
            ip_address text,
            user_agent text,
            created_at text not null
        );
        """
    )
    ensure_indexes(db)
    for key, label, order, is_bonus in STAGES:
        db.execute(
            """
            insert into stages (stage_key, label, sort_order, is_bonus, is_locked)
            values (?, ?, ?, ?, 0)
            on conflict(stage_key) do update set label = excluded.label, sort_order = excluded.sort_order, is_bonus = excluded.is_bonus
            """,
            (key, label, order, is_bonus),
        )
    for key, value in SETTINGS_DEFAULTS.items():
        db.execute("insert or ignore into settings (key, value) values (?, ?)", (key, value))
    ensure_settings_defaults(db)
    seed_bracket_placeholders(db)
    if not db.execute("select 1 from users where username = 'admin'").fetchone():
        db.execute(
            """
            insert into users (username, display_name, password_hash, is_admin, is_banned, created_at)
            values ('admin', 'Administrador', ?, 1, 0, ?)
            """,
            (generate_password_hash("admin123"), utc_now()),
        )
    if not db.execute("select 1 from games").fetchone():
        db.executemany(
            "insert into games (stage_key, starts_at, home_team, away_team) values (?, ?, ?, ?)",
            SEED_GAMES,
        )
    db.commit()


def table_exists(db: sqlite3.Connection, table: str) -> bool:
    return db.execute("select 1 from sqlite_master where type = 'table' and name = ?", (table,)).fetchone() is not None


def ensure_settings_defaults(db: sqlite3.Connection) -> None:
    for key, value in SETTINGS_DEFAULTS.items():
        db.execute("insert or ignore into settings (key, value) values (?, ?)", (key, value))
    db.execute(
        """
        update settings
        set value = '30'
        where key = 'auto_results_interval_seconds' and value = '120'
        """
    )
    db.execute(
        """
        update settings
        set value = '0'
        where key = 'auto_results_start_before_minutes' and value = '5'
        """
    )
    db.execute(
        """
        update settings
        set value = 'espn,promiedos,worldcup26,upbound'
        where key = 'auto_results_sources' and value = 'promiedos,espn,worldcup26,upbound'
        """
    )
    db.execute(
        """
        update settings
        set value = 'fecha_1,fecha_2,fecha_3,r32,r16,qf,sf,final'
        where key = 'auto_results_stage_keys' and value = 'fecha_1,fecha_2,fecha_3'
        """
    )


def ensure_indexes(db: sqlite3.Connection) -> None:
    if table_exists(db, "games"):
        db.execute("create unique index if not exists idx_games_external_id on games(external_id) where external_id is not null")
        db.execute("create index if not exists idx_games_stage_start on games(stage_key, starts_at, id)")
        db.execute(
            """
            create index if not exists idx_games_completed_order
            on games(starts_at, id)
            where home_score is not null and away_score is not null
            """
        )
    if table_exists(db, "predictions"):
        db.execute("create index if not exists idx_predictions_game_user on predictions(game_id, user_id)")
        db.execute("create index if not exists idx_predictions_user_game on predictions(user_id, game_id)")
    if table_exists(db, "chat_messages"):
        db.execute("create index if not exists idx_chat_messages_created on chat_messages(created_at, id)")
        db.execute("create index if not exists idx_chat_messages_user_created on chat_messages(user_id, created_at)")
    if table_exists(db, "audit_logs"):
        db.execute("create index if not exists idx_audit_logs_created on audit_logs(created_at)")
        db.execute("create index if not exists idx_audit_logs_user_created on audit_logs(user_id, created_at)")
    if table_exists(db, "sanctions"):
        db.execute("create index if not exists idx_sanctions_user_type_expires on sanctions(user_id, type, expires_at)")


def mark_existing_results_final(db: sqlite3.Connection) -> None:
    final_cutoff = (datetime.now(APP_TIMEZONE) - timedelta(minutes=140)).strftime("%Y-%m-%d %H:%M")
    db.execute(
        """
        update games
        set result_status = 'final'
        where result_status = 'pending'
          and home_score is not null
          and away_score is not null
          and starts_at <= ?
        """,
        (final_cutoff,),
    )


def current_database_name() -> str:
    name = session.get("database_name", "principal") if has_request_context() else "principal"
    return name if database_path_for_name(name).exists() else "principal"


def current_database_path() -> Path:
    return database_path_for_name(current_database_name())


def is_primary_database() -> bool:
    return current_database_name() == "principal"


def database_path_for_name(name: str) -> Path:
    if name == "principal":
        return DATABASE
    safe_name = safe_database_name(name)
    return DATABASE_DIR / f"{safe_name}.sqlite3"


def safe_database_name(name: str) -> str:
    name = (name or "").strip().lower()
    name = re.sub(r"[^a-z0-9_-]+", "-", name)
    return name.strip("-_")


def available_databases() -> list[dict]:
    DATABASE_DIR.mkdir(exist_ok=True)
    items = [{"name": "principal", "path": DATABASE, "primary": True}]
    for path in sorted(DATABASE_DIR.glob("*.sqlite3")):
        items.append({"name": path.stem, "path": path, "primary": False})
    return items


def current_page_label() -> str:
    endpoint = request.endpoint if has_request_context() else None
    return PAGE_LABELS.get(endpoint or "", "")


def accepted_current_terms(user: sqlite3.Row | None) -> bool:
    if not user or not user["accepted_terms_at"]:
        return False
    legal_updated_at = get_settings().get("legal_updated_at", "")
    return str(user["accepted_terms_at"]) >= str(legal_updated_at)


def asset_version(filename: str) -> int:
    path = BASE_DIR / "static" / filename
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 1


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    return g.db.execute(sql, params).fetchone()


def query_all(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return g.db.execute(sql, params).fetchall()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            return redirect(url_for("index"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            return redirect(url_for("index"))
        if not g.user["is_admin"]:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def debug_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            return redirect(url_for("index"))
        if not can_debug():
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def can_debug() -> bool:
    return bool(g.user and (g.user["is_admin"] or g.user["is_debugger"]))


def admin_count() -> int:
    return query_one("select count(*) as total from users where is_admin = 1")["total"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def format_datetime(value: str | None) -> str:
    if not value:
        return "-"
    raw = str(value)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return raw.replace("T", " ").split("+")[0]


def client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "-"


def client_agent() -> str:
    return (request.headers.get("User-Agent") or "-")[:300]


def rate_limited(key: str, limit: int, window_seconds: int) -> bool:
    now = time()
    window_start = now - window_seconds
    attempts = [stamp for stamp in RATE_LIMITS.get(key, []) if stamp >= window_start]
    limited = len(attempts) >= limit
    attempts.append(now)
    RATE_LIMITS[key] = attempts
    if len(RATE_LIMITS) > 2000:
        for old_key, values in list(RATE_LIMITS.items())[:500]:
            if not values or values[-1] < window_start:
                RATE_LIMITS.pop(old_key, None)
    return limited


def log_event(action: str, detail: str = "", user_id: int | None = None) -> None:
    actor_id = g.user["id"] if getattr(g, "user", None) else None
    if user_id is None:
        user_id = actor_id
    ip_address = client_ip() if has_request_context() else "auto"
    user_agent = client_agent() if has_request_context() else "auto-results-worker"
    g.db.execute(
        """
        insert into audit_logs (user_id, actor_id, action, detail, ip_address, user_agent, created_at)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, actor_id, action, detail[:800], ip_address, user_agent, utc_now()),
    )


def audit_groups(limit_per_user: int = 12) -> list[dict]:
    rows = query_all(
        """
        select audit_logs.*, users.username, users.display_name
        from audit_logs left join users on users.id = audit_logs.user_id
        order by audit_logs.id desc
        limit 500
        """
    )
    grouped: dict[str, dict] = {}
    for row in rows:
        key = str(row["user_id"]) if row["user_id"] is not None else "system"
        if key not in grouped:
            grouped[key] = {
                "username": row["username"] or "sistema",
                "display_name": row["display_name"] or "Eventos sin usuario",
                "count": 0,
                "last_at": row["created_at"],
                "logs": [],
            }
        group = grouped[key]
        group["count"] += 1
        if len(group["logs"]) < limit_per_user:
            group["logs"].append(row)
    return sorted(grouped.values(), key=lambda item: item["last_at"], reverse=True)


def wants_json() -> bool:
    return request.headers.get("X-Requested-With") == "fetch" or "application/json" in request.headers.get("Accept", "")


def prediction_error(message: str):
    if wants_json():
        return jsonify({"ok": False, "message": message}), 400
    flash(message, "error")
    return redirect(url_for("dashboard"))


def save_prediction(game: sqlite3.Row, home_goals: int, away_goals: int, penalty_winner: str | None = None) -> str | None:
    stage = query_one("select * from stages where stage_key = ?", (game["stage_key"],))
    if stage["is_locked"]:
        return "Esta etapa ya esta bloqueada."
    if not (0 <= home_goals <= 30 and 0 <= away_goals <= 30):
        return "Los goles tienen que estar entre 0 y 30."
    choice, stored_penalty_winner, error = prediction_choice_for_score(game, home_goals, away_goals, penalty_winner)
    if error:
        return error
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    g.db.execute(
        """
        insert into predictions (user_id, game_id, choice, home_goals, away_goals, penalty_winner, updated_at)
        values (?, ?, ?, ?, ?, ?, ?)
        on conflict(user_id, game_id) do update set
            choice = excluded.choice,
            home_goals = excluded.home_goals,
            away_goals = excluded.away_goals,
            penalty_winner = excluded.penalty_winner,
            updated_at = excluded.updated_at
        """,
        (g.user["id"], game["id"], choice, home_goals, away_goals, stored_penalty_winner, now),
    )
    penalty_detail = f"; {choice_label(game, stored_penalty_winner)} por penales" if stored_penalty_winner else ""
    log_event("prediction_save", f"{game['home_team']} vs {game['away_team']}: {home_goals}-{away_goals}{penalty_detail}")
    return None


def blank_to_none(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    return int(value)


def get_settings() -> dict[str, str]:
    rows = query_all("select key, value from settings")
    settings = SETTINGS_DEFAULTS.copy()
    settings.update({row["key"]: row["value"] for row in rows})
    return settings


def get_stages() -> list[sqlite3.Row]:
    return query_all("select * from stages order by sort_order")


def current_results_stage_key(stages: list[sqlite3.Row] | None = None) -> str:
    stages = stages or get_stages()
    if not stages:
        return "fecha_1"
    first_open_index = next((index for index, stage in enumerate(stages) if not stage["is_locked"]), None)
    if first_open_index is None:
        return stages[-1]["stage_key"]
    if first_open_index > 0:
        return stages[first_open_index - 1]["stage_key"]
    return stages[first_open_index]["stage_key"]


def admin_results_url() -> str:
    results_stage = request.form.get("results_stage", "").strip()
    if results_stage:
        return url_for("admin", results_stage=results_stage)
    return url_for("admin")


def stage_label(stage_key: str) -> str:
    return dict((key, label) for key, label, _order, _bonus in STAGES).get(stage_key, stage_key)


def team_label(name: str) -> Markup | str:
    normalized = normalize_team_name(name)
    code = TEAM_COUNTRY_CODES.get(normalized)
    if not code:
        return name
    safe_name = escape(name)
    flag_url = f"https://flagcdn.com/24x18/{code.lower()}.png"
    return Markup(f'<span class="team-label"><img class="flag" src="{flag_url}" alt=""> {safe_name}</span>')


def team_flag(name: str) -> Markup | str:
    normalized = normalize_team_name(name)
    code = TEAM_COUNTRY_CODES.get(normalized)
    if not code:
        return ""
    flag_url = f"https://flagcdn.com/24x18/{code.lower()}.png"
    safe_name = escape(name)
    return Markup(f'<img class="flag" src="{flag_url}" alt="{safe_name}">')


def team_select_options() -> list[dict[str, str]]:
    options = []
    for key, country_code in TEAM_COUNTRY_CODES.items():
        label = TEAM_DISPLAY_NAMES.get(key, key.title())
        emoji = TEAM_FLAGS.get(key) or flag_emoji(country_code)
        options.append({"value": label, "label": f"{emoji} {label}" if emoji else label, "key": normalize_team_name(label)})
    unique = {option["key"]: option for option in options}
    return sorted(unique.values(), key=lambda option: normalize_team_name(option["value"]))


def team_select_values() -> list[str]:
    return [option["value"] for option in team_select_options()]


def bracket_team_options() -> list[str]:
    return BRACKET_TEAM_OPTIONS


def normalize_team_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", (name or "").strip().lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def flag_emoji(country_code: str | None) -> str | None:
    if not country_code or len(country_code) != 2:
        return None
    base = 0x1F1E6
    return "".join(chr(base + ord(char) - ord("A")) for char in country_code.upper())


def choice_label(game: sqlite3.Row, choice: str | None) -> str:
    if choice == "home":
        return game["home_team"]
    if choice == "away":
        return game["away_team"]
    if choice == "draw":
        return "Empate"
    return "Sin elegir"


def row_value(row: sqlite3.Row | dict, key: str, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key] if key in row.keys() else default
    except (KeyError, AttributeError):
        return default


def clean_side_choice(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    return value if value in SIDE_CHOICES else None


def is_knockout_stage(stage_key: str | None) -> bool:
    return stage_key in KNOCKOUT_STAGE_KEYS


def needs_penalty_winner(stage_key: str | None, home_goals: int | None, away_goals: int | None) -> bool:
    return (
        is_knockout_stage(stage_key)
        and home_goals is not None
        and away_goals is not None
        and home_goals == away_goals
    )


def result_from_score(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if away_goals > home_goals:
        return "away"
    return "draw"


def result_from_score_and_penalties(
    stage_key: str | None,
    home_goals: int | None,
    away_goals: int | None,
    penalty_winner: str | None = None,
) -> str | None:
    if home_goals is None or away_goals is None:
        return None
    penalty_winner = clean_side_choice(penalty_winner)
    if needs_penalty_winner(stage_key, home_goals, away_goals) and penalty_winner:
        return penalty_winner
    return result_from_score(home_goals, away_goals)


def penalty_winner_for_result(
    stage_key: str | None,
    home_goals: int | None,
    away_goals: int | None,
    result: str | None,
) -> str | None:
    result = clean_side_choice(result)
    if needs_penalty_winner(stage_key, home_goals, away_goals) and result:
        return result
    return None


def prediction_choice_for_score(
    game: sqlite3.Row,
    home_goals: int,
    away_goals: int,
    penalty_winner: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    penalty_winner = clean_side_choice(penalty_winner)
    if needs_penalty_winner(game["stage_key"], home_goals, away_goals):
        if not penalty_winner:
            return None, None, "Elegi quien pasa por penales."
        return penalty_winner, penalty_winner, None
    return result_from_score(home_goals, away_goals), None, None


def game_result_status(game: sqlite3.Row) -> str:
    if "result_status" not in game.keys():
        return "pending"
    return str(game["result_status"] or "pending").strip().lower()


def game_has_score(game: sqlite3.Row) -> bool:
    return game["home_score"] is not None and game["away_score"] is not None


def game_is_final(game: sqlite3.Row) -> bool:
    return game_has_score(game) and game_result_status(game) in {"final", "manual"}


def game_is_live(game: sqlite3.Row) -> bool:
    return game_has_score(game) and game_result_status(game) == "live"


def game_status_label(game: sqlite3.Row) -> str:
    if game_is_final(game):
        return "Final"
    if game_is_live(game):
        return "Parcial"
    return "Pendiente"


def game_result(game: sqlite3.Row) -> str | None:
    if not game_is_final(game):
        return None
    penalty_winner = clean_side_choice(row_value(game, "result_penalty_winner"))
    if needs_penalty_winner(game["stage_key"], game["home_score"], game["away_score"]):
        if penalty_winner:
            return penalty_winner
        result = clean_side_choice(game["result"])
        return result
    return result_from_score(game["home_score"], game["away_score"])


def game_penalty_winner(game: sqlite3.Row) -> str | None:
    if not needs_penalty_winner(game["stage_key"], game["home_score"], game["away_score"]):
        return None
    explicit = clean_side_choice(row_value(game, "result_penalty_winner"))
    if explicit:
        return explicit
    result = game_result(game)
    return clean_side_choice(result)


def game_went_to_penalties(game: sqlite3.Row) -> bool:
    return game_penalty_winner(game) is not None


def result_detail_label(game: sqlite3.Row) -> str:
    result = game_result(game)
    if result is None:
        return "Sin resultado"
    label = choice_label(game, result)
    if game_went_to_penalties(game):
        return f"{label} por penales"
    return label


def stage_locked_and_played(stage: sqlite3.Row, games: list[sqlite3.Row]) -> bool:
    return bool(stage["is_locked"]) and bool(games) and all(game_result(game) for game in games)


def parse_game_start(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        starts_at = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=APP_TIMEZONE)
    return starts_at.astimezone(APP_TIMEZONE)


def format_game_datetime(value: str | None) -> str:
    starts_at = parse_game_start(value)
    if not starts_at:
        return format_datetime(value)
    return f"{starts_at.strftime('%d/%m %H:%M')} ARG"


def fixture_game_states(
    games: list[sqlite3.Row],
    now: datetime,
    mark_next: bool = False,
) -> tuple[dict[int, dict[str, str]], dict[str, int]]:
    pending_game_id = None
    next_game_id = None
    missing_games = []
    if mark_next:
        for game in games:
            if game_is_final(game) or game_is_live(game):
                continue
            starts_at = parse_game_start(game["starts_at"])
            missing_games.append((starts_at or datetime.max.replace(tzinfo=APP_TIMEZONE), game["id"]))
        overdue_games = [
            item
            for item in missing_games
            if item[0] != datetime.max.replace(tzinfo=APP_TIMEZONE) and now >= item[0] + MATCH_PENDING_AFTER
        ]
        if overdue_games:
            pending_game_id = min(overdue_games, key=lambda item: item[0])[1]
        next_candidates = [item for item in missing_games if item[1] != pending_game_id]
        if next_candidates:
            next_game_id = min(next_candidates, key=lambda item: item[0])[1]

    labels = {
        "final": "Final",
        "live": "Parcial",
        "pending": "Pendiente",
        "next": "Proximo",
        "upcoming": "Por disputar",
    }
    states: dict[int, dict[str, str]] = {}
    summary = {key: 0 for key in labels}
    for game in games:
        if game_is_final(game):
            key = "final"
        elif game_is_live(game):
            key = "live"
        elif pending_game_id == game["id"]:
            key = "pending"
        elif next_game_id == game["id"]:
            key = "next"
        else:
            key = "upcoming"
        summary[key] += 1
        states[game["id"]] = {"key": key, "label": labels[key]}
    return states, summary


def prediction_label(game: sqlite3.Row, prediction: sqlite3.Row | None) -> str:
    if not prediction:
        return "Sin cargar"
    score = ""
    if prediction["home_goals"] is not None and prediction["away_goals"] is not None:
        score = f" {prediction['home_goals']}-{prediction['away_goals']}"
    suffix = " por penales" if row_value(prediction, "penalty_winner") else ""
    return f"{choice_label(game, prediction['choice'])}{suffix}{score}"


def prediction_text(game: sqlite3.Row, home_goals: int, away_goals: int, penalty_winner: str | None = None) -> str:
    choice, stored_penalty_winner, _error = prediction_choice_for_score(game, home_goals, away_goals, penalty_winner)
    if choice is None:
        return f"Empate {home_goals}-{away_goals}"
    suffix = " por penales" if stored_penalty_winner else ""
    return f"{choice_label(game, choice)}{suffix} {home_goals}-{away_goals}"


def prediction_status(game: sqlite3.Row, prediction: sqlite3.Row | None) -> str:
    if not prediction:
        return "none"
    if game_result(game) is None:
        return "pending"
    points = prediction_points(prediction, game)
    if points == 3:
        return "exact"
    if points == 1:
        return "hit"
    return "miss"


def prediction_status_label(game: sqlite3.Row, prediction: sqlite3.Row | None) -> str:
    status = prediction_status(game, prediction)
    labels = {
        "pending": "Pendiente de resultado",
        "exact": "Marcador exacto: +3 pts",
        "hit": "Resultado correcto: +1 pt",
        "miss": "Fallaste: 0 pts",
    }
    return labels.get(status, "Sin prediccion")


def prediction_points(prediction: sqlite3.Row, game: sqlite3.Row) -> int:
    result = game_result(game)
    if result is None:
        return 0
    result_hit = prediction["choice"] == result
    if (
        result_hit
        and prediction["home_goals"] is not None
        and prediction["away_goals"] is not None
        and game["home_score"] is not None
        and game["away_score"] is not None
        and prediction["home_goals"] == game["home_score"]
        and prediction["away_goals"] == game["away_score"]
    ):
        return 3
    if result_hit:
        return 1
    return 0


def chat_message_payload(message: sqlite3.Row) -> dict:
    return {
        "id": message["id"],
        "user_id": message["user_id"],
        "display_name": message["username"],
        "username": message["username"],
        "body": "[mensaje moderado]" if message["is_deleted"] else message["body"],
        "created_at": message["created_at"],
        "is_deleted": bool(message["is_deleted"]),
        "is_banned": bool(message["is_banned"]),
    }


def chat_user_payload(user: sqlite3.Row) -> dict:
    return {
        "id": user["id"],
        "display_name": user["username"],
        "username": user["username"],
        "is_admin": bool(user["is_admin"]),
        "is_banned": bool(user["is_banned"]),
    }


def touch_chat_presence() -> None:
    if g.user:
        now = utc_now()
        g.db.execute("update users set last_seen_at = ?, chat_seen_at = ? where id = ?", (now, now, g.user["id"]))
        g.db.commit()


def chat_presence_cutoff() -> str:
    return datetime.fromtimestamp(datetime.now().timestamp() - 30, timezone.utc).isoformat(timespec="seconds")


def leaderboard(stage_key: str | None = None, include_admins: bool = False) -> list[dict]:
    if include_admins:
        users = query_all("select * from users order by is_admin desc, is_debugger desc, username")
    else:
        users = query_all("select * from users where is_admin = 0 and is_debugger = 0 order by username")
    rows = []
    for user in users:
        stages = user_stage_scores(user["id"])
        exact_scores = user_exact_scores(user["id"])
        hit_scores = user_hit_scores(user["id"])
        total = stages.get(stage_key, 0) if stage_key else sum(stages.values())
        exact_total = exact_scores.get(stage_key, 0) if stage_key else sum(exact_scores.values())
        hit_total = hit_scores.get(stage_key, 0) if stage_key else sum(hit_scores.values())
        rows.append({
            "user": user,
            "total": total,
            "stages": stages,
            "hits": hit_total,
            "exact": exact_total,
            "hits_by_stage": hit_scores,
            "exact_by_stage": exact_scores,
        })
    return sorted(rows, key=lambda row: (-row["total"], row["user"]["username"].lower()))


def user_stage_scores(user_id: int) -> dict[str, int]:
    scores = {stage[0]: 0 for stage in STAGES}
    rows = query_all(
        """
        select predictions.*, games.stage_key, games.home_score, games.away_score, games.result, games.result_penalty_winner, games.result_status
        from predictions join games on games.id = predictions.game_id
        where predictions.user_id = ?
          and games.result_status in ('final', 'manual')
          and games.home_score is not null
          and games.away_score is not null
        """,
        (user_id,),
    )
    for row in rows:
        scores[row["stage_key"]] += prediction_points(row, row)
    return scores


def user_exact_scores(user_id: int) -> dict[str, int]:
    scores = {stage[0]: 0 for stage in STAGES}
    rows = query_all(
        """
        select predictions.*, games.stage_key, games.home_score, games.away_score, games.result, games.result_penalty_winner, games.result_status
        from predictions join games on games.id = predictions.game_id
        where predictions.user_id = ?
          and games.result_status in ('final', 'manual')
          and games.home_score is not null
          and games.away_score is not null
        """,
        (user_id,),
    )
    for row in rows:
        if prediction_points(row, row) == 3:
            scores[row["stage_key"]] += 1
    return scores


def user_hit_scores(user_id: int) -> dict[str, int]:
    scores = {stage[0]: 0 for stage in STAGES}
    rows = query_all(
        """
        select predictions.*, games.stage_key, games.home_score, games.away_score, games.result, games.result_penalty_winner, games.result_status
        from predictions join games on games.id = predictions.game_id
        where predictions.user_id = ?
          and games.result_status in ('final', 'manual')
          and games.home_score is not null
          and games.away_score is not null
        """,
        (user_id,),
    )
    for row in rows:
        if row["choice"] == game_result(row):
            scores[row["stage_key"]] += 1
    return scores


def stage_leaderboards(include_admins: bool = False) -> dict[str, list[dict]]:
    rows = leaderboard(include_admins=include_admins)
    boards: dict[str, list[dict]] = {}
    for key, _label, _order, _bonus in STAGES:
        boards[key] = sorted(
            [
                {
                    "user": row["user"],
                    "points": row["stages"].get(key, 0),
                    "hits": row["hits_by_stage"].get(key, 0),
                    "exact": row["exact_by_stage"].get(key, 0),
                }
                for row in rows
            ],
            key=lambda item: (-item["points"], item["user"]["username"].lower()),
        )
    return boards


def ranking_image_payload() -> dict:
    boards = [
        ranking_image_board_payload(
            "general",
            "Tabla general",
            "Suma de todas las etapas",
            leaderboard(),
        )
    ]
    for stage in get_stages():
        boards.append(
            ranking_image_board_payload(
                stage["stage_key"],
                stage["label"],
                f"Tabla {stage['label']}",
                leaderboard(stage["stage_key"]),
            )
        )
    return {"boards": boards}


def ranking_image_board_payload(key: str, title: str, subtitle: str, rows: list[dict]) -> dict:
    return {
        "key": key,
        "title": title,
        "subtitle": subtitle,
        "rows": [
            {
                "rank": index,
                "user": row["user"]["username"],
                "marker": f"{row['hits']}/{row['exact']}",
                "points": row["total"],
            }
            for index, row in enumerate(rows, start=1)
        ],
    }


def historical_progress() -> dict:
    users = query_all("select * from users where is_admin = 0 and is_debugger = 0 order by username")
    games = query_all(
        """
        select *
        from games
        where result_status in ('final', 'manual')
          and home_score is not null
          and away_score is not null
        order by starts_at, id
        """
    )
    predictions = {
        (row["user_id"], row["game_id"]): row
        for row in query_all("select * from predictions")
    }
    totals = {
        user["id"]: {
            "user": user,
            "total": 0,
            "stage_total": 0,
            "hits": 0,
            "stage_hits": 0,
            "exact": 0,
            "stage_exact": 0,
            "series": [0],
            "stage_series": [0],
        }
        for user in users
    }
    groups_by_stage: dict[str, dict] = {}
    labels = [{"text": "Inicio", "detail": "Inicio", "short": "Inicio", "stage_key": None, "stage_label": ""}]
    latest_event = None
    current_stage_key = None

    for game in games:
        stage_key = game["stage_key"]
        if stage_key != current_stage_key:
            current_stage_key = stage_key
            for item in totals.values():
                item["stage_total"] = 0
                item["stage_hits"] = 0
                item["stage_exact"] = 0
        for user in users:
            prediction = predictions.get((user["id"], game["id"]))
            points = prediction_points(prediction, game) if prediction else 0
            totals[user["id"]]["total"] += points
            totals[user["id"]]["stage_total"] += points
            if prediction and game_result(game) == prediction["choice"]:
                totals[user["id"]]["hits"] += 1
                totals[user["id"]]["stage_hits"] += 1
            if prediction and prediction_points(prediction, game) == 3:
                totals[user["id"]]["exact"] += 1
                totals[user["id"]]["stage_exact"] += 1
            totals[user["id"]]["series"].append(totals[user["id"]]["total"])
            totals[user["id"]]["stage_series"].append(totals[user["id"]]["stage_total"])

        board = sorted(
            [
                {
                    "user": item["user"],
                    "total": item["total"],
                    "hits": item["hits"],
                    "exact": item["exact"],
                }
                for item in totals.values()
            ],
            key=lambda row: (-row["total"], row["user"]["username"].lower()),
        )
        stage_board = sorted(
            [
                {
                    "user": item["user"],
                    "total": item["stage_total"],
                    "hits": item["stage_hits"],
                    "exact": item["stage_exact"],
                }
                for item in totals.values()
            ],
            key=lambda row: (-row["total"], row["user"]["username"].lower()),
        )
        penalty_suffix = f" ({choice_label(game, game_penalty_winner(game))} por penales)" if game_went_to_penalties(game) else ""
        game_label = f"{game['home_team']} {game['home_score']}:{game['away_score']} {game['away_team']}{penalty_suffix}"
        short_label = f"{game['home_team']} {game['home_score']}:{game['away_score']} {game['away_team']}"
        event = {
            "game": game,
            "label": game_label,
            "short_label": short_label,
            "board": board,
            "stage_board": stage_board,
        }
        current_stage_label = stage_label(stage_key)
        labels.append(
            {
                "text": short_label,
                "detail": game_label,
                "short": short_label,
                "stage_key": stage_key,
                "stage_label": current_stage_label,
            }
        )
        if stage_key not in groups_by_stage:
            groups_by_stage[stage_key] = {"stage_key": stage_key, "label": current_stage_label, "events": []}
        groups_by_stage[stage_key]["events"].append(event)
        latest_event = event

    groups = [groups_by_stage[key] for key, _label, _order, _bonus in STAGES if key in groups_by_stage]
    return {
        "groups": groups,
        "chart": history_chart_model(users, totals, labels, series_key="series", total_key="total", point_label="pts acumulados"),
        "stage_chart": history_chart_model(users, totals, labels, series_key="stage_series", total_key="stage_total", point_label="pts en la etapa"),
        "latest_event": latest_event,
    }


def history_chart_model(
    users: list[sqlite3.Row],
    totals: dict[int, dict],
    labels: list[dict],
    series_key: str = "series",
    total_key: str = "total",
    point_label: str = "pts acumulados",
) -> dict:
    event_count = max(1, len(labels) - 1)
    width = max(1320, 130 + event_count * 110)
    height = 540
    left = 52
    right = 28
    top = 32
    bottom = 112
    max_points = max([max(item[series_key] or [0]) for item in totals.values()] + [1])
    steps = max(1, len(labels) - 1)
    palette = [
        "#86dec2",
        "#f2d58a",
        "#9ed0f5",
        "#f0a2a2",
        "#c4a7f5",
        "#8bd17c",
        "#f5a97f",
        "#7dd3fc",
        "#f7b7d2",
        "#d8c36a",
    ]

    def point_for(index: int, value: int) -> tuple[float, float]:
        x = left + ((width - left - right) * index / steps)
        y = top + ((height - top - bottom) * (max_points - value) / max_points)
        return x, y

    series = []
    for index, user in enumerate(users):
        values = totals[user["id"]][series_key]
        points = [point_for(point_index, value) for point_index, value in enumerate(values)]
        series.append(
            {
                "user": user,
                "color": palette[index % len(palette)],
                "points": " ".join(f"{x:.1f},{y:.1f}" for x, y in points),
                "dots": [
                    {
                        "x": f"{x:.1f}",
                        "y": f"{y:.1f}",
                        "value": values[point_index],
                        "delta": values[point_index] - (values[point_index - 1] if point_index else 0),
                        "label": labels[point_index]["detail"],
                    }
                    for point_index, (x, y) in enumerate(points)
                ],
                "total": totals[user["id"]][total_key],
            }
        )

    ticks = []
    tick_step = max(1, len(labels) // 10)
    for index, label in enumerate(labels):
        if index not in {0, len(labels) - 1} and index % tick_step != 0:
            continue
        x, _y = point_for(index, 0)
        ticks.append({"x": f"{x:.1f}", "label": label["short"]})

    stage_ranges = []
    step_width = (width - left - right) / steps
    index = 1
    while index < len(labels):
        stage_key = labels[index].get("stage_key")
        if not stage_key:
            index += 1
            continue
        start_index = index
        while index + 1 < len(labels) and labels[index + 1].get("stage_key") == stage_key:
            index += 1
        end_index = index
        start_x, _ = point_for(start_index, 0)
        end_x, _ = point_for(end_index, 0)
        x1 = max(left, start_x - step_width / 2)
        x2 = min(width - right, end_x + step_width / 2)
        stage_ranges.append(
            {
                "label": labels[start_index]["stage_label"],
                "x1": f"{x1:.1f}",
                "x2": f"{x2:.1f}",
                "x": f"{((x1 + x2) / 2):.1f}",
                "width": f"{max(0, x2 - x1):.1f}",
            }
        )
        index += 1

    grid = []
    for step in range(0, 5):
        value = round(max_points * step / 4)
        _x, y = point_for(0, value)
        grid.append({"value": value, "y": f"{y:.1f}"})

    return {
        "width": width,
        "height": height,
        "max_points": max_points,
        "point_label": point_label,
        "series": series,
        "ticks": ticks,
        "stage_ranges": stage_ranges,
        "grid": grid,
        "plot_top": top,
        "plot_bottom": height - bottom,
        "tick_y1": height - 110,
        "tick_y2": height - 102,
        "tick_label_y": height - 72,
        "stage_band_y": height - 44,
        "stage_band_height": 30,
        "stage_label_y": height - 23,
    }


def prediction_progress(user_id: int) -> list[dict]:
    rows = []
    for stage in get_stages():
        total = query_one("select count(*) as total from games where stage_key = ?", (stage["stage_key"],))["total"]
        loaded = query_one(
            """
            select count(*) as total
            from predictions join games on games.id = predictions.game_id
            where predictions.user_id = ? and games.stage_key = ?
            """,
            (user_id, stage["stage_key"]),
        )["total"]
        rows.append({"stage": stage, "loaded": loaded, "total": total})
    return rows


def admin_prediction_audit(users: list[sqlite3.Row], stages: list[sqlite3.Row]) -> dict[int, dict]:
    first_open_index = next((index for index, stage in enumerate(stages) if not stage["is_locked"]), None)
    available_stages = stages if first_open_index is None else stages[: first_open_index + 1]
    available_stage_keys = {stage["stage_key"] for stage in available_stages}
    stage_totals = {
        row["stage_key"]: row["total"]
        for row in query_all("select stage_key, count(*) as total from games group by stage_key")
    }
    audit_stages = [stage for stage in stages if stage_totals.get(stage["stage_key"], 0) > 0]
    stage_keys = [stage["stage_key"] for stage in audit_stages]
    loaded_by_user_stage: dict[tuple[int, str], int] = {}
    if stage_keys:
        placeholders = ",".join("?" for _ in stage_keys)
        rows = query_all(
            f"""
            select predictions.user_id, games.stage_key, count(*) as total
            from predictions join games on games.id = predictions.game_id
            where games.stage_key in ({placeholders})
            group by predictions.user_id, games.stage_key
            """,
            tuple(stage_keys),
        )
        loaded_by_user_stage = {
            (row["user_id"], row["stage_key"]): row["total"]
            for row in rows
        }

    audit: dict[int, dict] = {}
    for user in users:
        stage_rows = []
        loaded_total = 0
        available_total = 0
        tournament_loaded_total = 0
        tournament_total = 0
        for stage in audit_stages:
            total = stage_totals.get(stage["stage_key"], 0)
            loaded = loaded_by_user_stage.get((user["id"], stage["stage_key"]), 0)
            is_available = stage["stage_key"] in available_stage_keys
            tournament_loaded_total += loaded
            tournament_total += total
            if is_available:
                loaded_total += loaded
                available_total += total
            stage_rows.append(
                {
                    "stage": stage,
                    "loaded": loaded,
                    "total": total,
                    "available": is_available,
                    "complete": is_available and total > 0 and loaded >= total,
                }
            )
        audit[user["id"]] = {
            "loaded": loaded_total,
            "total": available_total,
            "complete": available_total > 0 and loaded_total >= available_total,
            "tournament_loaded": tournament_loaded_total,
            "tournament_total": tournament_total,
            "future_total": max(0, tournament_total - available_total),
            "stages": stage_rows,
        }
    return audit


def stage_winners() -> dict[str, dict]:
    winners = {}
    boards = stage_leaderboards()
    for stage in get_stages():
        board = boards.get(stage["stage_key"], [])
        top_points = board[0]["points"] if board else 0
        if top_points <= 0:
            winners[stage["stage_key"]] = {"points": 0, "users": [], "count": 0}
            continue
        users = [row["user"]["username"] for row in board if row["points"] == top_points]
        winners[stage["stage_key"]] = {"points": top_points, "users": users, "count": len(users)}
    return winners


def rank_badge(index: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(index, "")


def seed_fake_users(count: int) -> int:
    created = 0
    for index in range(1, count + 1):
        username = f"debug{index:02d}"
        if query_one("select 1 from users where username = ?", (username,)):
            continue
        g.db.execute(
            """
            insert into users (username, display_name, password_hash, is_admin, is_debugger, is_banned, created_at)
            values (?, ?, ?, 0, 0, 0, ?)
            """,
            (username, f"Usuario Debug {index:02d}", generate_password_hash("debug123"), utc_now()),
        )
        created += 1
    g.db.commit()
    return created


def seed_fake_predictions(stage_key: str) -> int:
    users = query_all("select * from users where is_banned = 0 and is_admin = 0 and is_debugger = 0")
    games = query_all("select * from games where stage_key = ? order by starts_at, id", (stage_key,))
    created = 0
    for user in users:
        for game in games:
            home_goals = random.randint(0, 4)
            away_goals = random.randint(0, 4)
            penalty_winner = random.choice(("home", "away")) if needs_penalty_winner(game["stage_key"], home_goals, away_goals) else None
            choice = result_from_score_and_penalties(game["stage_key"], home_goals, away_goals, penalty_winner)
            g.db.execute(
                """
                insert into predictions (user_id, game_id, choice, home_goals, away_goals, penalty_winner, updated_at)
                values (?, ?, ?, ?, ?, ?, ?)
                on conflict(user_id, game_id) do update set
                    choice = excluded.choice,
                    home_goals = excluded.home_goals,
                    away_goals = excluded.away_goals,
                    penalty_winner = excluded.penalty_winner,
                    updated_at = excluded.updated_at
                """,
                (user["id"], game["id"], choice, home_goals, away_goals, penalty_winner, utc_now()),
            )
            created += 1
    g.db.commit()
    return created


def seed_fake_results(stage_key: str) -> int:
    games = query_all("select * from games where stage_key = ?", (stage_key,))
    for game in games:
        home_score = random.randint(0, 4)
        away_score = random.randint(0, 4)
        penalty_winner = random.choice(("home", "away")) if needs_penalty_winner(game["stage_key"], home_score, away_score) else None
        result = result_from_score_and_penalties(game["stage_key"], home_score, away_score, penalty_winner)
        g.db.execute(
            "update games set home_score = ?, away_score = ?, result = ?, result_penalty_winner = ?, result_status = 'final' where id = ?",
            (home_score, away_score, result, penalty_winner, game["id"]),
        )
    g.db.commit()
    return len(games)


def create_backup(kind: str, stage_key: str | None = None) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if kind == "full":
        data = {table: dump_table(table) for table in ["users", "stages", "games", "predictions", "settings", "chat_messages", "sanctions"]}
    elif kind == "users":
        data = {table: dump_table(table) for table in ["users", "predictions", "sanctions"]}
    elif kind == "chat":
        data = {table: dump_table(table) for table in ["chat_messages", "sanctions"]}
    elif kind == "stage":
        if not stage_key:
            abort(400)
        data = {
            "stage_key": stage_key,
            "games": dump_query("select * from games where stage_key = ? order by starts_at, id", (stage_key,)),
            "predictions": dump_query(
                """
                select predictions.*
                from predictions join games on games.id = predictions.game_id
                where games.stage_key = ?
                order by predictions.user_id, predictions.game_id
                """,
                (stage_key,),
            ),
        }
    else:
        abort(404)
    path = BACKUP_DIR / f"{timestamp}-{kind}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def create_sqlite_backup(prefix: str | None = None) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    db_name = current_database_name()
    label = f"{prefix}-" if prefix else ""
    path = BACKUP_DIR / f"{timestamp}-{label}{db_name}-database.sqlite3"
    source = sqlite3.connect(current_database_path())
    try:
        target = sqlite3.connect(path)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return path


def restore_sqlite_backup(uploaded) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = BACKUP_DIR / f"restore-upload-{secrets.token_hex(8)}.sqlite3"
    uploaded.save(temp_path)
    try:
        validate_sqlite_backup(temp_path)
        target = current_database_path()
        g.db.close()
        g.pop("db", None)
        forget_runtime_schema(target)
        shutil.copy2(temp_path, target)
        forget_runtime_schema(target)
    finally:
        temp_path.unlink(missing_ok=True)


def validate_sqlite_backup(path: Path) -> None:
    required_tables = {"users", "stages", "games", "predictions", "settings"}
    try:
        db = sqlite3.connect(path)
        try:
            integrity = db.execute("pragma integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError("El archivo SQLite no paso el control de integridad.")
            tables = {row[0] for row in db.execute("select name from sqlite_master where type = 'table'")}
        finally:
            db.close()
    except sqlite3.DatabaseError as exc:
        raise ValueError("El archivo no parece ser una base SQLite valida.") from exc
    missing = required_tables - tables
    if missing:
        raise ValueError(f"El backup no corresponde a esta app. Faltan tablas: {', '.join(sorted(missing))}.")


def backup_status(limit: int = 5) -> dict:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted((path for path in BACKUP_DIR.iterdir() if path.is_file()), key=lambda item: item.stat().st_mtime, reverse=True)
    return {
        "total": len(files),
        "latest": [
            {
                "name": path.name,
                "size": human_size(path.stat().st_size),
                "created": datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m/%Y %H:%M"),
            }
            for path in files[:limit]
        ],
    }


def human_size(size: int) -> str:
    value = float(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024


def dump_table(table: str) -> list[dict]:
    return dump_query(f"select * from {table}")


def dump_query(sql: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in query_all(sql, params)]


def prize_rows() -> list[dict]:
    settings = get_settings()
    participants = query_one(
        "select count(*) as total from users where is_admin = 0 and is_debugger = 0 and is_banned = 0"
    )["total"]
    pool = participants * float(settings["entry_price"] or 0)
    rows = []
    for pos in range(1, 7):
        pct = float(settings.get(f"podium_{pos}_percent", 0) or 0)
        rows.append({"name": f"Puesto {pos}", "percent": pct, "amount": pool * pct / 100})
    bonus_pct = float(settings.get("bonus_percent", 0) or 0)
    for key, label, _order, is_bonus in STAGES:
        if is_bonus:
            rows.append({"name": f"Bonus {label}", "percent": bonus_pct, "amount": pool * bonus_pct / 100})
    return rows


def start_auto_results_worker(app: Flask) -> None:
    global AUTO_RESULTS_WORKER_STARTED
    if os.environ.get("PRODE_AUTO_RESULTS_WORKER", "1").lower() in {"0", "false", "no"}:
        return
    with AUTO_RESULTS_WORKER_LOCK:
        if AUTO_RESULTS_WORKER_STARTED:
            return
        AUTO_RESULTS_WORKER_STARTED = True
    thread = threading.Thread(target=auto_results_worker, args=(app,), name="auto-results-worker", daemon=True)
    thread.start()


def auto_results_worker(app: Flask) -> None:
    sleep(5)
    while True:
        interval = int(SETTINGS_DEFAULTS["auto_results_interval_seconds"])
        try:
            with app.app_context():
                g.db = get_db()
                ensure_runtime_schema(g.db)
                settings = get_settings()
                interval = auto_int(settings.get("auto_results_interval_seconds"), interval, 30, 3600)
                if setting_enabled(settings.get("auto_fixture_sync_enabled"), default=True):
                    sync_fixture_if_due(settings)
                if setting_enabled(settings.get("auto_results_enabled")):
                    sync_auto_results_once(manual=False)
        except Exception as exc:
            try:
                with app.app_context():
                    g.db = get_db()
                    ensure_runtime_schema(g.db)
                    set_setting("auto_results_last_run_at", utc_now())
                    set_setting("auto_results_last_summary", f"Error worker: {exc}")
                    g.db.commit()
            except Exception:
                pass
        sleep(max(30, interval))


def sync_auto_results_once(manual: bool = False) -> dict:
    settings = get_settings()
    stats = {
        "checked": 0,
        "due": 0,
        "updated": 0,
        "schedule_updated": 0,
        "unchanged": 0,
        "missing": 0,
        "skipped": 0,
        "sources": [],
        "errors": [],
    }
    if not manual and not setting_enabled(settings.get("auto_results_enabled")):
        return stats

    games = auto_results_due_games(settings)
    stats["due"] = len(games)
    if not games:
        update_auto_results_status(stats)
        return stats

    source_names = auto_result_source_names(settings)
    snapshots_by_source: dict[str, list[dict]] = {}
    for source in source_names:
        try:
            snapshots = load_auto_result_source(source, games, settings)
            snapshots_by_source[source] = snapshots
            stats["sources"].append(f"{source}:{len(snapshots)}")
        except Exception as exc:
            stats["errors"].append(f"{source}: {friendly_source_error(source, exc)}")

    stats["schedule_updated"] = reconcile_auto_kickoffs(snapshots_by_source, source_names, settings)
    if stats["schedule_updated"]:
        games = auto_results_due_games(settings)
        stats["due"] = len(games)

    apply_provisional = setting_enabled(settings.get("auto_results_apply_provisional"), default=True)
    for game in games:
        stats["checked"] += 1
        snapshot = find_auto_result_snapshot(game, snapshots_by_source, source_names)
        if not snapshot:
            stats["missing"] += 1
            continue
        kickoff_updated = update_game_kickoff_from_auto_snapshot(game, snapshot)
        if snapshot.get("home_score") is None or snapshot.get("away_score") is None:
            if kickoff_updated:
                stats["updated"] += 1
            else:
                stats["missing"] += 1
            continue
        if not snapshot.get("started") and not snapshot.get("completed"):
            if clear_unstarted_auto_result(game, snapshot):
                stats["updated"] += 1
            elif kickoff_updated:
                stats["updated"] += 1
            else:
                stats["missing"] += 1
            continue
        if not apply_provisional and not snapshot.get("completed"):
            stats["skipped"] += 1
            continue
        if update_game_from_auto_snapshot(game, snapshot):
            stats["updated"] += 1
        elif kickoff_updated:
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1

    update_auto_results_status(stats)
    g.db.commit()
    return stats


def auto_results_flash_message(stats: dict) -> str:
    base = (
        f"Auto resultados: {stats['updated']} resultados actualizados, "
        f"{stats.get('schedule_updated', 0)} horarios, {stats['unchanged']} sin cambios, "
        f"{stats['missing']} sin dato, {stats['skipped']} omitidos."
    )
    if stats["errors"]:
        return f"{base} Errores: {' | '.join(stats['errors'][:3])}"
    return base


def update_auto_results_status(stats: dict) -> None:
    summary = auto_results_flash_message(stats)
    set_setting("auto_results_last_run_at", utc_now())
    set_setting("auto_results_last_summary", summary)


def set_setting(key: str, value: str) -> None:
    g.db.execute(
        "insert into settings (key, value) values (?, ?) on conflict(key) do update set value = excluded.value",
        (key, value),
    )


def sync_fixture_if_due(settings: dict) -> None:
    interval_minutes = auto_int(settings.get("auto_fixture_sync_interval_minutes"), 30, 5, 1440)
    last_run = parse_iso_datetime(settings.get("auto_fixture_sync_last_run_at"))
    now = datetime.now(timezone.utc)
    if last_run and now - last_run < timedelta(minutes=interval_minutes):
        return
    try:
        stats = sync_promiedos_fixture()
        summary = (
            f"Fixture auto: {stats['created']} creados, "
            f"{stats['updated']} actualizados, {stats['skipped']} omitidos."
        )
    except Exception as exc:
        summary = f"Error fixture auto: {friendly_source_error('promiedos', exc)}"
    set_setting("auto_fixture_sync_last_run_at", utc_now())
    set_setting("auto_fixture_sync_last_summary", summary)
    g.db.commit()


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def auto_results_due_games(settings: dict) -> list[sqlite3.Row]:
    stage_keys = auto_result_stage_keys(settings)
    placeholders = ",".join("?" for _ in stage_keys)
    games = query_all(
        f"""
        select *
        from games
        where stage_key in ({placeholders})
        order by starts_at, id
        """,
        tuple(stage_keys),
    )
    now = datetime.now(APP_TIMEZONE)
    start_before = timedelta(minutes=auto_int(settings.get("auto_results_start_before_minutes"), 0, 0, 30))
    halftime_minutes = auto_int(settings.get("auto_results_halftime_minutes"), 45, 30, 70)
    halftime_retry_minutes = auto_int(settings.get("auto_results_halftime_retry_minutes"), 20, 1, 60)
    fulltime_minutes = auto_int(settings.get("auto_results_fulltime_minutes"), 90, 70, 140)
    fulltime_retry_minutes = auto_int(settings.get("auto_results_fulltime_retry_minutes"), 45, 1, 120)
    catchup_hours = auto_int(settings.get("auto_results_catchup_hours"), 72, 1, 240)
    due = []
    for game in games:
        starts_at = parse_game_start(game["starts_at"])
        if not starts_at:
            continue
        result_status = game["result_status"] if "result_status" in game.keys() else "pending"
        if result_status == "manual":
            continue
        halftime_start = starts_at + timedelta(minutes=halftime_minutes) - start_before
        halftime_end = starts_at + timedelta(minutes=halftime_minutes + halftime_retry_minutes)
        fulltime_start = starts_at + timedelta(minutes=fulltime_minutes) - start_before
        fulltime_end = starts_at + timedelta(minutes=fulltime_minutes + fulltime_retry_minutes)
        catchup_end = starts_at + timedelta(hours=catchup_hours)
        in_halftime_window = halftime_start <= now <= halftime_end
        in_fulltime_window = fulltime_start <= now <= fulltime_end
        in_catchup_window = now >= starts_at + timedelta(minutes=fulltime_minutes)
        if result_status == "final" and now > catchup_end:
            in_catchup_window = False
        if in_halftime_window or in_fulltime_window or in_catchup_window:
            due.append(game)
    return due


def auto_result_stage_keys(settings: dict) -> list[str]:
    keys = []
    for raw in (settings.get("auto_results_stage_keys") or "").split(","):
        key = raw.strip()
        if key in AUTO_RESULT_STAGE_LIMIT and key not in keys:
            keys.append(key)
    return keys or ["fecha_1", "fecha_2", "fecha_3"]


def auto_result_source_names(settings: dict) -> list[str]:
    names = []
    for raw in (settings.get("auto_results_sources") or "").split(","):
        name = raw.strip().lower()
        if name in AUTO_RESULT_SOURCES and name not in names:
            names.append(name)
    return names or ["espn", "promiedos", "worldcup26", "upbound"]


def load_auto_result_source(source: str, games: list[sqlite3.Row], settings: dict) -> list[dict]:
    if source == "promiedos":
        return load_promiedos_auto_snapshots(settings)
    if source == "espn":
        return load_espn_auto_snapshots(games, settings)
    if source == "worldcup26":
        return load_worldcup26_auto_snapshots(settings)
    if source == "upbound":
        return load_upbound_auto_snapshots(settings)
    raise ValueError(f"Fuente no soportada: {source}")


def load_promiedos_auto_snapshots(settings: dict) -> list[dict]:
    snapshots = []
    seen: set[str] = set()
    for round_number in promiedos_rounds(settings.get("promiedos_group_rounds", "1,2,3")):
        url = settings["promiedos_games_url_template"].format(round=round_number)
        data = fetch_promiedos_json(url, settings.get("promiedos_x_ver", "1.11.7.5"))
        for raw_game in data.get("games", []):
            stage_key = promiedos_stage_key(raw_game.get("stage_round_name", f"Fecha {round_number}"))
            if stage_key not in AUTO_RESULT_STAGE_LIMIT:
                continue
            parsed = parse_promiedos_game(stage_key, raw_game)
            if not parsed or parsed["external_id"] in seen:
                continue
            seen.add(parsed["external_id"])
            snapshots.append(auto_snapshot_from_promiedos(parsed, raw_game))
    return snapshots


def auto_snapshot_from_promiedos(parsed: dict, raw_game: dict) -> dict:
    home_score = parsed["home_score"]
    away_score = parsed["away_score"]
    status_text = auto_status_text(raw_game)
    completed = promiedos_completed(raw_game)
    started = completed or promiedos_started(raw_game)
    penalty_winner = penalty_winner_for_result(parsed["stage_key"], home_score, away_score, parsed["result"]) if completed else None
    return {
        "source": "promiedos",
        "source_id": parsed["external_id"],
        "home": parsed["home_team"],
        "away": parsed["away_team"],
        "home_score": home_score,
        "away_score": away_score,
        "result": parsed["result"],
        "result_penalty_winner": penalty_winner,
        "completed": completed,
        "started": started,
        "status": status_text,
        "kickoff": parse_game_start(parsed["starts_at"]),
    }


def load_espn_auto_snapshots(games: list[sqlite3.Row], settings: dict) -> list[dict]:
    base_url = (settings.get("espn_scoreboard_url") or SETTINGS_DEFAULTS["espn_scoreboard_url"]).strip()
    dates = sorted(
        {
            (parse_game_start(game["starts_at"]) or datetime.now(APP_TIMEZONE)).strftime("%Y%m%d")
            for game in games
        }
    )
    snapshots = []
    for date in dates:
        data = fetch_json_url(f"{base_url}?dates={date}")
        for event in data.get("events", []):
            competition = first_item(event.get("competitions"))
            competitors = competition.get("competitors", []) if isinstance(competition, dict) else []
            home = first_matching(competitors, "home")
            away = first_matching(competitors, "away")
            if not home or not away:
                continue
            status = competition.get("status", {}) if isinstance(competition, dict) else {}
            status_type = status.get("type", {}) if isinstance(status, dict) else {}
            home_team = home.get("team", {})
            away_team = away.get("team", {})
            kickoff = parse_source_datetime(competition.get("date") or event.get("date"))
            period = safe_int(status.get("period")) or 0
            home_score = safe_int(home.get("score"))
            away_score = safe_int(away.get("score"))
            completed = bool(status_type.get("completed"))
            winner = None
            if completed:
                if home.get("winner") is True:
                    winner = "home"
                elif away.get("winner") is True:
                    winner = "away"
            result = None
            if home_score is not None and away_score is not None:
                result = winner if home_score == away_score and winner else result_from_score(home_score, away_score)
            snapshots.append(
                {
                    "source": "espn",
                    "source_id": str(event.get("id") or ""),
                    "home": home_team.get("displayName") or home_team.get("name") or "",
                    "away": away_team.get("displayName") or away_team.get("name") or "",
                    "home_score": home_score,
                    "away_score": away_score,
                    "result": result,
                    "result_penalty_winner": winner if home_score is not None and away_score is not None and home_score == away_score else None,
                    "completed": completed,
                    "started": status_type.get("state") != "pre" or period > 0,
                    "status": first_non_empty(status_type.get("shortDetail"), status_type.get("detail"), status_type.get("description")),
                    "kickoff": kickoff,
                }
            )
    return snapshots


def load_worldcup26_auto_snapshots(settings: dict) -> list[dict]:
    url = (settings.get("worldcup26_api_url") or SETTINGS_DEFAULTS["worldcup26_api_url"]).strip()
    data = fetch_json_url(url)
    snapshots = []
    for game in data.get("games", []):
        home = first_non_empty(game.get("home_team_name_en"), game.get("home_team_label"))
        away = first_non_empty(game.get("away_team_name_en"), game.get("away_team_label"))
        if not home or not away:
            continue
        status = str(game.get("time_elapsed") or "")
        completed = str(game.get("finished") or "").lower() == "true" or "finished" in status.lower()
        home_score = safe_int(game.get("home_score"))
        away_score = safe_int(game.get("away_score"))
        snapshots.append(
            {
                "source": "worldcup26",
                "source_id": str(game.get("id") or ""),
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
                "result": result_from_score(home_score, away_score) if home_score is not None and away_score is not None else None,
                "result_penalty_winner": None,
                "completed": completed,
                "started": completed or status.lower() not in {"", "notstarted", "not started"},
                "status": status,
                "kickoff": None,
            }
        )
    return snapshots


def load_upbound_auto_snapshots(settings: dict) -> list[dict]:
    url = (settings.get("upbound_worldcup_url") or SETTINGS_DEFAULTS["upbound_worldcup_url"]).strip()
    data = fetch_json_url(url)
    snapshots = []
    for raw in data.get("matches", []):
        home = raw.get("team1") or ""
        away = raw.get("team2") or ""
        if not home or not away:
            continue
        ft = ((raw.get("score") or {}).get("ft") or [])
        completed = isinstance(ft, list) and len(ft) >= 2
        home_score = safe_int(ft[0]) if completed else None
        away_score = safe_int(ft[1]) if completed else None
        snapshots.append(
            {
                "source": "upbound",
                "source_id": "",
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
                "result": result_from_score(home_score, away_score) if home_score is not None and away_score is not None else None,
                "result_penalty_winner": None,
                "completed": completed,
                "started": completed,
                "status": "FT" if completed else "scheduled/no live score",
                "kickoff": parse_upbound_datetime(raw),
            }
        )
    return snapshots


def find_auto_result_snapshot(game: sqlite3.Row, snapshots_by_source: dict[str, list[dict]], source_order: list[str]) -> dict | None:
    matches = []
    for source_index, source in enumerate(source_order):
        for snapshot in snapshots_by_source.get(source, []):
            oriented = orient_auto_snapshot_for_game(game, snapshot)
            if oriented:
                oriented = dict(oriented)
                oriented["_source_order"] = source_index
                matches.append(oriented)
    if not matches:
        return None
    return max(matches, key=auto_snapshot_priority)


def auto_snapshot_priority(snapshot: dict) -> tuple[int, int, int, int]:
    has_score = snapshot.get("home_score") is not None and snapshot.get("away_score") is not None
    return (
        1 if snapshot.get("completed") else 0,
        1 if snapshot.get("started") else 0,
        1 if has_score else 0,
        -int(snapshot.get("_source_order", 0)),
    )


def reconcile_auto_kickoffs(
    snapshots_by_source: dict[str, list[dict]],
    source_names: list[str],
    settings: dict,
) -> int:
    stage_keys = auto_result_stage_keys(settings)
    placeholders = ",".join("?" for _ in stage_keys)
    games = query_all(
        f"""
        select *
        from games
        where stage_key in ({placeholders})
        order by starts_at, id
        """,
        tuple(stage_keys),
    )
    updated = 0
    for game in games:
        snapshot = find_auto_result_snapshot(game, snapshots_by_source, source_names)
        if snapshot and update_game_kickoff_from_auto_snapshot(game, snapshot):
            updated += 1
    return updated


def orient_auto_snapshot_for_game(game: sqlite3.Row, snapshot: dict) -> dict | None:
    game_external_id = str(game["external_id"] or "")
    if game_external_id and snapshot.get("source") == "promiedos" and game_external_id == str(snapshot.get("source_id") or ""):
        return snapshot
    game_start = parse_game_start(game["starts_at"])
    source_start = snapshot.get("kickoff")
    if game_start and source_start and abs((game_start - source_start).total_seconds()) > 18 * 3600:
        return None
    game_home = auto_team_key(game["home_team"])
    game_away = auto_team_key(game["away_team"])
    source_home = auto_team_key(snapshot.get("home", ""))
    source_away = auto_team_key(snapshot.get("away", ""))
    if game_home == source_home and game_away == source_away:
        return snapshot
    if game_home == source_away and game_away == source_home:
        oriented = dict(snapshot)
        oriented["home"] = snapshot.get("away")
        oriented["away"] = snapshot.get("home")
        oriented["home_score"] = snapshot.get("away_score")
        oriented["away_score"] = snapshot.get("home_score")
        if snapshot.get("result") == "home":
            oriented["result"] = "away"
        elif snapshot.get("result") == "away":
            oriented["result"] = "home"
        if snapshot.get("result_penalty_winner") == "home":
            oriented["result_penalty_winner"] = "away"
        elif snapshot.get("result_penalty_winner") == "away":
            oriented["result_penalty_winner"] = "home"
        return oriented
    return None


def update_game_from_auto_snapshot(game: sqlite3.Row, snapshot: dict) -> bool:
    home_score = snapshot["home_score"]
    away_score = snapshot["away_score"]
    result = result_from_score(home_score, away_score)
    result_penalty_winner = None
    if bool(snapshot.get("completed")):
        result_penalty_winner = penalty_winner_for_result(
            game["stage_key"],
            home_score,
            away_score,
            snapshot.get("result_penalty_winner") or snapshot.get("result") or result,
        )
        if result_penalty_winner:
            result = result_penalty_winner
    result_status = source_result_status(
        bool(snapshot.get("completed")),
        result,
        bool(snapshot.get("started") or snapshot.get("completed")),
    )
    current_status = game["result_status"] if "result_status" in game.keys() else "pending"
    if (
        game["home_score"] == home_score
        and game["away_score"] == away_score
        and game["result"] == result
        and row_value(game, "result_penalty_winner") == result_penalty_winner
        and current_status == result_status
    ):
        return False
    g.db.execute(
        "update games set home_score = ?, away_score = ?, result = ?, result_penalty_winner = ?, result_status = ? where id = ?",
        (home_score, away_score, result, result_penalty_winner, result_status, game["id"]),
    )
    penalty_detail = f"; {choice_label(game, result_penalty_winner)} por penales" if result_penalty_winner else ""
    log_event(
        "auto_result_update",
        f"{stage_label(game['stage_key'])}: {game['home_team']} {home_score}-{away_score} {game['away_team']} "
        f"({snapshot.get('source')}; {result_status}{penalty_detail}; {snapshot.get('status') or 'sin estado'})",
    )
    return True


def clear_unstarted_auto_result(game: sqlite3.Row, snapshot: dict) -> bool:
    current_status = game["result_status"] if "result_status" in game.keys() else "pending"
    if current_status != "live":
        return False
    if game["home_score"] is None and game["away_score"] is None and game["result"] is None:
        return False
    g.db.execute(
        "update games set home_score = null, away_score = null, result = null, result_penalty_winner = null, result_status = 'pending' where id = ?",
        (game["id"],),
    )
    log_event(
        "auto_result_clear",
        f"{stage_label(game['stage_key'])}: {game['home_team']} vs {game['away_team']} vuelve a pendiente "
        f"({snapshot.get('source')}; {snapshot.get('status') or 'no iniciado'})",
    )
    return True


def update_game_kickoff_from_auto_snapshot(game: sqlite3.Row, snapshot: dict) -> bool:
    kickoff = snapshot.get("kickoff")
    current_row = query_one("select starts_at from games where id = ?", (game["id"],))
    current_start_text = current_row["starts_at"] if current_row else game["starts_at"]
    current_start = parse_game_start(current_start_text)
    if not kickoff or not current_start:
        return False
    if abs((kickoff - current_start).total_seconds()) < 15 * 60:
        return False
    starts_at = kickoff.strftime("%Y-%m-%d %H:%M")
    g.db.execute("update games set starts_at = ? where id = ?", (starts_at, game["id"]))
    log_event(
        "auto_kickoff_update",
        f"{stage_label(game['stage_key'])}: {game['home_team']} vs {game['away_team']} horario {current_start_text} -> {starts_at} "
        f"({snapshot.get('source')})",
    )
    return True


def fetch_json_url(url: str, headers: dict | None = None, timeout: int = 20) -> dict:
    request_obj = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "ProdeMundial2026/auto-results",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(request_obj, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def auto_team_key(name: str) -> str:
    normalized = normalize_team_name(name)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    return AUTO_TEAM_ALIASES.get(normalized, normalized)


def parse_source_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(APP_TIMEZONE)


def parse_upbound_datetime(raw: dict) -> datetime | None:
    date = str(raw.get("date") or "")
    time_text = str(raw.get("time") or "")
    match = re.match(r"^(?P<h>\d{1,2}):(?P<m>\d{2})\s+UTC(?P<sign>[+-])(?P<offset>\d{1,2})$", time_text)
    if not match:
        return None
    try:
        day = datetime.strptime(date, "%Y-%m-%d")
        hour = int(match.group("h"))
        minute = int(match.group("m"))
        offset = int(match.group("offset"))
    except ValueError:
        return None
    if match.group("sign") == "-":
        offset *= -1
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone(timedelta(hours=offset))).astimezone(APP_TIMEZONE)


def auto_status_text(value: dict) -> str:
    parts = []
    for key in ("status", "status_name", "state", "time", "time_elapsed", "game_time", "minute"):
        raw = value.get(key)
        if isinstance(raw, dict):
            for subkey in ("name", "short_name", "symbol_name", "description", "detail"):
                text = str(raw.get(subkey) or "").strip()
                if text:
                    parts.append(text)
            enum = raw.get("enum")
            if enum is not None:
                parts.append(str(enum))
            continue
        text = str(raw or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def promiedos_status_enum(game: dict) -> int | None:
    status = game.get("status")
    if isinstance(status, dict):
        return safe_int(status.get("enum"))
    return None


def promiedos_completed(game: dict) -> bool:
    status_enum = promiedos_status_enum(game)
    if status_enum == 3:
        return True
    status_text = auto_status_text(game).lower()
    return "finalizado" in status_text or re.search(r"\b(final|fin)\b", status_text) is not None


def promiedos_started(game: dict) -> bool:
    status_enum = promiedos_status_enum(game)
    if status_enum is not None:
        return status_enum >= 2
    status_text = auto_status_text(game).lower()
    if any(token in status_text for token in ("programado", "no iniciado", "not started", "scheduled")):
        return False
    scores = game.get("scores") or []
    return safe_score(scores, 0) is not None and safe_score(scores, 1) is not None


def source_result_status(completed: bool, result: str | None, started: bool = True) -> str:
    if completed and result:
        return "final"
    if started and result:
        return "live"
    return "pending"


def first_item(value):
    return value[0] if isinstance(value, list) and value else {}


def first_matching(items: list, home_away: str) -> dict | None:
    for item in items:
        if item.get("homeAway") == home_away:
            return item
    return None


def first_non_empty(*values) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text.lower() != "none":
            return text
    return ""


def safe_int(value) -> int | None:
    if isinstance(value, dict):
        value = value.get("score") or value.get("value")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def setting_enabled(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def auto_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        parsed = default
    return min(max(parsed, minimum), maximum)


def friendly_source_error(source: str, exc: Exception) -> str:
    text = str(exc)
    if source == "worldcup26" and "SSL" in repr(exc).upper():
        return "fallo SSL/TLS del servidor"
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    return text[:180]


def sync_promiedos_fixture() -> dict[str, int]:
    settings = get_settings()
    stats = {"created": 0, "updated": 0, "skipped": 0}
    seen_external_ids: set[str] = set()
    seen_stage_keys: set[str] = set()
    for round_number in promiedos_rounds(settings.get("promiedos_group_rounds", "1,2,3")):
        url = settings["promiedos_games_url_template"].format(round=round_number)
        data = fetch_promiedos_json(url, settings.get("promiedos_x_ver", "1.11.7.5"))
        for game in data.get("games", []):
            stage_key = promiedos_stage_key(game.get("stage_round_name", f"Fecha {round_number}"))
            if not stage_key:
                stats["skipped"] += 1
                continue
            if import_promiedos_game(game, stage_key, stats, seen_external_ids):
                seen_stage_keys.add(stage_key)
    data = fetch_promiedos_json(settings["fixture_api_url"], settings.get("promiedos_x_ver", "1.11.7.5"))
    games_section = data.get("games", {})
    if not isinstance(games_section, dict):
        g.db.commit()
        return stats
    filters = games_section.get("filters", [])
    for fixture_filter in filters:
        stage_key = promiedos_stage_key(fixture_filter.get("name", ""))
        if not stage_key:
            stats["skipped"] += len(fixture_filter.get("games", []))
            continue
        for game in fixture_filter.get("games", []):
            if import_promiedos_game(game, stage_key, stats, seen_external_ids):
                seen_stage_keys.add(stage_key)
    if seen_external_ids:
        remove_seed_games()
        remove_bracket_placeholders(seen_stage_keys)
    g.db.commit()
    return stats


def promiedos_rounds(value: str) -> list[int]:
    rounds = []
    for part in value.split(","):
        part = part.strip()
        if part.isdigit():
            rounds.append(int(part))
    return rounds or [1, 2, 3]


def import_promiedos_game(game: dict, stage_key: str, stats: dict[str, int], seen_external_ids: set[str]) -> bool:
    parsed = parse_promiedos_game(stage_key, game)
    if not parsed:
        stats["skipped"] += 1
        return False
    if parsed["external_id"] in seen_external_ids:
        return True
    seen_external_ids.add(parsed["external_id"])
    existing = query_one("select id, fixture_manual from games where external_id = ?", (parsed["external_id"],))
    result_status = source_result_status(promiedos_completed(game), parsed["result"], promiedos_started(game))
    penalty_winner = penalty_winner_for_result(
        parsed["stage_key"],
        parsed["home_score"],
        parsed["away_score"],
        parsed["result"],
    ) if result_status == "final" else None
    result = penalty_winner or parsed["result"]
    if existing:
        if existing["fixture_manual"]:
            stats["skipped"] += 1
            return True
        g.db.execute(
            """
            update games
            set stage_key = ?, starts_at = ?, home_team = ?, away_team = ?,
                home_score = ?, away_score = ?, result = ?, result_penalty_winner = ?, result_status = ?
            where id = ?
            """,
            (
                parsed["stage_key"],
                parsed["starts_at"],
                parsed["home_team"],
                parsed["away_team"],
                parsed["home_score"],
                parsed["away_score"],
                result,
                penalty_winner,
                result_status,
                existing["id"],
            ),
        )
        stats["updated"] += 1
        return True
    else:
        g.db.execute(
            """
            insert into games (external_id, stage_key, starts_at, home_team, away_team, home_score, away_score, result, result_penalty_winner, result_status)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed["external_id"],
                parsed["stage_key"],
                parsed["starts_at"],
                parsed["home_team"],
                parsed["away_team"],
                parsed["home_score"],
                parsed["away_score"],
                result,
                penalty_winner,
                result_status,
            ),
        )
        stats["created"] += 1
        return True


def remove_seed_games() -> None:
    for stage_key, starts_at, home_team, away_team in SEED_GAMES:
        g.db.execute(
            """
            delete from games
            where external_id is null and stage_key = ? and starts_at = ? and home_team = ? and away_team = ?
            """,
            (stage_key, starts_at, home_team, away_team),
        )


def remove_bracket_placeholders(stage_keys: set[str]) -> None:
    bracket_stage_keys = {key for key, _label, order, _bonus in STAGES if order >= 4}
    for stage_key in sorted(stage_keys & bracket_stage_keys):
        g.db.execute(
            "delete from games where stage_key = ? and external_id like ? and fixture_manual = 0",
            (stage_key, f"visual-bracket-{stage_key}-%"),
        )


def seed_bracket_placeholders(db: sqlite3.Connection) -> None:
    for index, (stage_key, starts_at, home_team, away_team) in enumerate(BRACKET_PLACEHOLDER_GAMES, start=1):
        external_id = f"visual-bracket-{stage_key}-{index}"
        existing = db.execute("select id from games where external_id = ?", (external_id,)).fetchone()
        if existing:
            db.execute(
                "update games set stage_key = ?, starts_at = ?, home_team = ?, away_team = ? where external_id = ? and fixture_manual = 0",
                (stage_key, starts_at, home_team, away_team, external_id),
            )
        else:
            db.execute(
                "insert into games (external_id, stage_key, starts_at, home_team, away_team) values (?, ?, ?, ?, ?)",
                (external_id, stage_key, starts_at, home_team, away_team),
            )


def fetch_promiedos_json(url: str, x_ver: str) -> dict:
    request_obj = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.promiedos.com.ar/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
            "x-ver": x_ver,
        },
    )
    with urllib.request.urlopen(request_obj, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def promiedos_stage_key(name: str) -> str | None:
    normalized = name.strip().lower()
    return PROMIEDOS_STAGE_MAP.get(normalized)


def parse_promiedos_game(stage_key: str, game: dict) -> dict | None:
    teams = game.get("teams") or []
    if len(teams) < 2:
        return None
    external_id = str(game.get("id") or "").strip()
    start_time = parse_promiedos_datetime(game.get("start_time", ""))
    if not external_id or not start_time:
        return None
    scores = game.get("scores") or []
    home_score = safe_score(scores, 0)
    away_score = safe_score(scores, 1)
    return {
        "external_id": external_id,
        "stage_key": stage_key,
        "starts_at": start_time,
        "home_team": teams[0].get("name", "Local"),
        "away_team": teams[1].get("name", "Visitante"),
        "home_score": home_score,
        "away_score": away_score,
        "result": promiedos_result(stage_key, game, home_score, away_score),
    }


def parse_promiedos_datetime(value: str) -> str | None:
    for fmt in ("%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return None


def safe_score(scores: list, index: int) -> int | None:
    try:
        value = scores[index]
    except (IndexError, TypeError):
        return None
    if isinstance(value, dict):
        value = value.get("score") or value.get("value")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def promiedos_result(stage_key: str | None, game: dict, home_score: int | None, away_score: int | None) -> str | None:
    if home_score is not None and away_score is not None:
        if home_score != away_score:
            return result_from_score(home_score, away_score)
        if not needs_penalty_winner(stage_key, home_score, away_score):
            return "draw"
    winner = game.get("winner")
    if winner == 0:
        return "home"
    if winner == 1:
        return "away"
    if winner == -2:
        return "draw"
    if home_score is not None and away_score is not None:
        if home_score > away_score:
            return "home"
        if away_score > home_score:
            return "away"
        return "draw"
    return None


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    app = create_app()
    with app.app_context():
        db = get_db()
        db.executescript(
            """
            create table if not exists users (
                id integer primary key autoincrement,
                username text not null unique,
                display_name text not null,
                password_hash text not null,
                is_admin integer not null default 0,
                is_debugger integer not null default 0,
                is_banned integer not null default 0,
                last_seen_at text,
                chat_seen_at text,
                created_at text not null
            );
            create table if not exists stages (
                stage_key text primary key,
                label text not null,
                sort_order integer not null,
                is_bonus integer not null default 0,
                is_locked integer not null default 0
            );
            create table if not exists games (
                id integer primary key autoincrement,
                external_id text unique,
                stage_key text not null references stages(stage_key),
                starts_at text not null,
                home_team text not null,
                away_team text not null,
                home_score integer,
                away_score integer,
                result text,
                result_penalty_winner text,
                result_status text not null default 'pending',
                fixture_manual integer not null default 0
            );
            create table if not exists predictions (
                id integer primary key autoincrement,
                user_id integer not null references users(id),
                game_id integer not null references games(id),
                choice text not null,
                home_goals integer,
                away_goals integer,
                penalty_winner text,
                updated_at text not null,
                unique(user_id, game_id)
            );
            create table if not exists settings (
                key text primary key,
                value text not null
            );
            create table if not exists chat_messages (
                id integer primary key autoincrement,
                user_id integer not null references users(id),
                body text not null,
                created_at text not null,
                is_deleted integer not null default 0
            );
            create table if not exists sanctions (
                id integer primary key autoincrement,
                user_id integer not null references users(id),
                admin_id integer not null references users(id),
                type text not null,
                reason text not null,
                expires_at text,
                created_at text not null
            );
            create table if not exists audit_logs (
                id integer primary key autoincrement,
                user_id integer,
                actor_id integer,
                action text not null,
                detail text,
                ip_address text,
                user_agent text,
                created_at text not null
            );
            """
        )
        ensure_column(db, "games", "external_id", "text")
        ensure_column(db, "games", "result_status", "text not null default 'pending'")
        ensure_column(db, "games", "result_penalty_winner", "text")
        mark_existing_results_final(db)
        ensure_column(db, "users", "last_seen_at", "text")
        ensure_column(db, "users", "chat_seen_at", "text")
        ensure_column(db, "users", "is_debugger", "integer not null default 0")
        ensure_column(db, "users", "force_password_change", "integer not null default 0")
        ensure_column(db, "users", "accepted_terms_at", "text")
        ensure_column(db, "games", "external_id", "text")
        ensure_column(db, "games", "result_status", "text not null default 'pending'")
        ensure_column(db, "games", "result_penalty_winner", "text")
        ensure_column(db, "games", "fixture_manual", "integer not null default 0")
        ensure_column(db, "predictions", "home_goals", "integer")
        ensure_column(db, "predictions", "away_goals", "integer")
        ensure_column(db, "predictions", "penalty_winner", "text")
        ensure_indexes(db)
        for key, label, order, is_bonus in STAGES:
            db.execute(
                """
                insert into stages (stage_key, label, sort_order, is_bonus, is_locked)
                values (?, ?, ?, ?, 0)
                on conflict(stage_key) do update set label = excluded.label, sort_order = excluded.sort_order, is_bonus = excluded.is_bonus
                """,
                (key, label, order, is_bonus),
            )
        for key, value in SETTINGS_DEFAULTS.items():
            db.execute("insert or ignore into settings (key, value) values (?, ?)", (key, value))
        ensure_settings_defaults(db)
        db.execute(
            """
            update settings
            set value = ?
            where key = 'fixture_api_url' and value = 'https://api.promiedos.com.ar/league/games/bac/102_69_4_1'
            """,
            (SETTINGS_DEFAULTS["fixture_api_url"],),
        )
        seed_bracket_placeholders(db)
        if not db.execute("select 1 from users where username = 'admin'").fetchone():
            db.execute(
                """
                insert into users (username, display_name, password_hash, is_admin, is_banned, created_at)
                values ('admin', 'Administrador', ?, 1, 0, ?)
                """,
                (generate_password_hash("admin123"), utc_now()),
            )
        if not db.execute("select 1 from games").fetchone():
            db.executemany(
                "insert into games (stage_key, starts_at, home_team, away_team) values (?, ?, ?, ?)",
                SEED_GAMES,
            )
        db.commit()


def ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = [row["name"] for row in db.execute(f"pragma table_info({table})")]
    if column not in columns:
        db.execute(f"alter table {table} add column {column} {definition}")


app = create_app()


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(host="0.0.0.0", port=port, debug=debug)
