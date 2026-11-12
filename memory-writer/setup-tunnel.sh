#!/bin/bash
# Cria o túnel SSH do PC local (192.168.1.170) para o Strata no PC-SALA (192.168.1.184).
# Após rodar, o endpoint fica em http://127.0.0.1:18081 (equivalente a 127.0.0.1:8081 no remoto).
#
# Uso:  ./setup-tunnel.sh          # inicia em background
#       ./setup-tunnel.sh check    # verifica se o túnel responde
#       ./setup-tunnel.sh stop     # mata o túnel

set -euo pipefail
PIDFILE="$HOME/.strata-tunnel.pid"
LOG="$HOME/.strata-tunnel.log"

case "${1:-start}" in
  start)
    if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Túnel já está rodando (PID $(cat "$PIDFILE"))"
      exit 0
    fi
    nohup ssh -F /dev/null -i "$HOME/.ssh/id_ed25519" \
      -N -L 18081:127.0.0.1:8081 \
      -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
      igor@192.168.1.184 >"$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 2
    echo "Túnel iniciado (PID $(cat "$PIDFILE")) — 127.0.0.1:18081 -> 192.168.1.184:8081"
    ;;
  check)
    curl -s --max-time 5 http://127.0.0.1:18081/v1/models | head -c 400
    echo
    ;;
  stop)
    if [[ -f "$PIDFILE" ]]; then
      kill "$(cat "$PIDFILE")" 2>/dev/null || true
      rm -f "$PIDFILE"
      echo "Túnel parado."
    else
      echo "Sem PID file."
    fi
    ;;
esac
