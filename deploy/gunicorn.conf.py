"""
Gunicorn settings for AttendPro (used by deploy/attendpro.service).

The server is shared with another site, so AttendPro keeps a small, fixed
pool: 3 workers x 2 threads handles many organisations scanning at once.
"""
# Nginx talks to Gunicorn over this socket (systemd creates /run/attendpro)
bind = "unix:/run/attendpro/gunicorn.sock"

workers = 3
threads = 2
worker_class = "gthread"

# Long enough for big Excel exports
timeout = 120
graceful_timeout = 30
keepalive = 5

# Recycle workers now and then so memory stays steady
max_requests = 1000
max_requests_jitter = 100

# Logs go to journald: journalctl -u attendpro -f
accesslog = "-"
errorlog = "-"
loglevel = "info"
proc_name = "attendpro"
