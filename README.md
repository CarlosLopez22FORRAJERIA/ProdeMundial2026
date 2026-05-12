# Prode Mundial 2026

App privada en Python + Flask + SQLite para un prode del Mundial 2026.

## Que incluye

- Login con usuarios creados por admin.
- Predicciones por marcador.
- Etapas: Fecha 1, Fecha 2, Fecha 3, 16vos, 8vos, 4tos, semis y final.
- Bloqueo manual de etapas desde admin.
- Tabla general y tablas por etapa.
- Premios configurables.
- Chat general con moderacion, bans, timeouts y auditoria.
- Fixture con resultados y sincronizacion configurable desde admin.
- Bases sandbox para pruebas.

## Correr local

```bash
python -m pip install -r requirements.txt
python app.py
```

Abrir:

```txt
http://127.0.0.1:5000
```

Usuario inicial:

- Usuario: `admin`
- Clave: `admin123`

## Deploy Linux

Para produccion, definir `PRODE_SECRET_KEY` con un valor privado y correr con un servidor WSGI.

```bash
python -m pip install -r requirements.txt
export PRODE_SECRET_KEY="cambiar-por-un-secreto-largo"
python -c "from app import init_db; init_db()"
gunicorn app:app --bind 0.0.0.0:8000
```

## Deploy en Render

El proyecto ya incluye `render.yaml`.

Pasos recomendados:

1. Subir este proyecto a un repo de GitHub.
2. En Render, crear un Blueprint desde ese repo usando `render.yaml`.
3. Render va a crear un Web Service Python con disco persistente.
4. La app inicia con:

```bash
python -c "from app import init_db; init_db()" && gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
```

Variables usadas en Render:

- `PRODE_DATA_DIR=/var/data`
- `PRODE_SECRET_KEY` generado por Render

Archivos persistentes:

```txt
/var/data/prode.sqlite3
/var/data/databases
/var/data/backups
```

Importante: sin disco persistente, SQLite se pierde en redeploys/restarts. Para esta app conviene usar siempre disk en Render.
