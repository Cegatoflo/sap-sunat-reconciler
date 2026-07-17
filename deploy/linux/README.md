# Despliegue en Linux (CentOS / Ubuntu)

La aplicación es **cross-platform** (FastAPI + SQLite + React corren igual en Linux). Lo único
específico de cada SO son los scripts de arranque: en Windows se usa **NSSM + Programador de
tareas** (carpeta `deploy/`), y en Linux el equivalente es **systemd + timer/cron + nginx**.

> Estos manifiestos están escritos y son correctos para systemd/nginx, pero **no vienen
> "probados en producción" en esta máquina** — están pensados como base lista para adaptar
> (rutas, usuario de servicio, `server_name`, certificados).

## Supuestos

| Cosa | Valor de ejemplo |
|---|---|
| Ruta del proyecto | `/opt/conciliador` |
| Usuario de servicio | `conciliador` (sin shell de login) |
| Puerto interno del backend | `127.0.0.1:18450` (solo local; nginx expone el 443) |
| `.env` | `/opt/conciliador/.env` (la app lo carga por ruta absoluta) |

## Pasos

```bash
# 1) Usuario de servicio y ubicación
sudo useradd --system --home /opt/conciliador --shell /usr/sbin/nologin conciliador
sudo mkdir -p /opt/conciliador && sudo chown conciliador:conciliador /opt/conciliador
# (copia aquí el proyecto: /opt/conciliador/backend, /opt/conciliador/frontend, .env, ...)

# 2) Entorno del backend
cd /opt/conciliador/backend
python3 -m venv .venv
.venv/bin/pip install -r ../requirements.txt

# 3) Frontend compilado (el backend lo sirve si frontend/dist existe)
cd /opt/conciliador/frontend
npm install && npm run build

# 4) Servicio del backend
sudo cp /opt/conciliador/deploy/linux/conciliador-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now conciliador-backend
systemctl status conciliador-backend

# 5) Job nocturno de pre-carga (timer de systemd)
sudo cp /opt/conciliador/deploy/linux/conciliador-refrescar.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now conciliador-refrescar.timer
systemctl list-timers conciliador-refrescar.timer

# 6) TLS público con nginx
sudo cp /opt/conciliador/deploy/linux/nginx.conf.example /etc/nginx/conf.d/conciliador.conf
# edita server_name y las rutas de los certificados
sudo nginx -t && sudo systemctl reload nginx
```

## Notas por distro

- **Ubuntu/Debian**: `nologin` suele estar en `/usr/sbin/nologin`. nginx desde `apt`.
- **CentOS/RHEL/Rocky**: `nologin` en `/sbin/nologin`. Con **SELinux** activo, permite que
  nginx haga proxy hacia el backend: `sudo setsebool -P httpd_can_network_connect 1`.
- **Firewall**: abre solo 80/443 (`firewalld`/`ufw`); el 18450 queda cerrado al exterior.

## Logs

- Backend: `journalctl -u conciliador-backend -f`
- Job nocturno: `journalctl -u conciliador-refrescar -f`
