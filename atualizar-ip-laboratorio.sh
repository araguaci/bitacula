#!/usr/bin/env bash
# Troca o IP público do laboratório nas portas de banco (3306, 6379, 5432).
# Use depois que a rede do laboratório reiniciar e o IP público mudar.
#
# Não use "restrict-db-ports.sh --ip=...": esse comando substitui a lista
# inteira e remove a outra estação já liberada.
#
# Uso:
#   sudo ./atualizar-ip-laboratorio.sh NOVO.IP.PUBLICO
#   sudo ./atualizar-ip-laboratorio.sh --show
#
# No laboratório, use o IP público que o servidor enxerga.
# O endereço da rede local não chega até aqui. Descubra o público com:
#   curl -4 ifconfig.me

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "${BITACULA_IP_CONF:-}" ]; then
    CONF_FILE="$BITACULA_IP_CONF"
elif [ -f /etc/artesdosul/workstation-ip.conf ]; then
    CONF_FILE="/etc/artesdosul/workstation-ip.conf"
else
    CONF_FILE="/etc/bitacula/workstations.conf"
fi
STATE_FILE="${ROOT}/laboratorio.ip"
RESTRICT="/usr/local/sbin/restrict-db-ports.sh"
PORTS=(3306 6379 5432)

usage() {
    cat <<'EOF'
Uso:
  sudo ./atualizar-ip-laboratorio.sh NOVO.IP.PUBLICO
  sudo ./atualizar-ip-laboratorio.sh --show

Exemplo, depois de um reboot da rede do laboratório:
  curl -4 ifconfig.me          # rode isto no laboratório
  sudo ./atualizar-ip-laboratorio.sh 203.0.113.10
EOF
    exit 0
}

valid_ipv4() {
    local ip=$1
    [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
    local IFS=.
    # shellcheck disable=SC2086
    set -- $ip
    [ "$1" -le 255 ] && [ "$2" -le 255 ] && [ "$3" -le 255 ] && [ "$4" -le 255 ]
}

need_root() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "Execute como root."
        exit 1
    fi
}

show() {
    echo "=== IP do laboratório registrado ==="
    if [ -f "$STATE_FILE" ]; then
        cat "$STATE_FILE"
    else
        echo "(ainda não registrado)"
    fi
    echo
    echo "=== $CONF_FILE ==="
    cat "$CONF_FILE" 2>/dev/null || echo "(não existe)"
    echo
    echo "=== ADS_DB_PORTS ==="
    iptables -L ADS_DB_PORTS -n --line-numbers 2>/dev/null || echo "(cadeia ausente)"
    echo
    echo "=== UFW (portas de banco) ==="
    ufw status | grep -E '3306|6379|5432' || true
}

remove_ufw_ip() {
    local ip=$1
    local guard=0
    local num
    [ -n "$ip" ] || return 0
    while [ "$guard" -lt 20 ]; do
        num=$(ufw status numbered | sed -nE "s/^\[ *([0-9]+)\].*(3306|6379|5432)\/tcp.*${ip//./\\.}.*/\1/p" | head -1)
        [ -z "$num" ] && break
        ufw --force delete "$num" >/dev/null
        echo "UFW: removida regra do IP antigo $ip (#$num)"
        guard=$((guard + 1))
    done
}

allow_ufw_ip() {
    local ip=$1
    local port
    for port in "${PORTS[@]}"; do
        if ufw status | grep -q "${port}/tcp.*${ip}"; then
            echo "UFW: $port já liberada para $ip"
        else
            ufw allow from "$ip" to any port "$port" proto tcp comment "Lab TimeFlow DB" >/dev/null
            echo "UFW: $port liberada para $ip"
        fi
    done
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
fi

need_root

if [ "${1:-}" = "--show" ] || [ -z "${1:-}" ]; then
    show
    [ -n "${1:-}" ] || usage
    exit 0
fi

NEW_IP=$1
if ! valid_ipv4 "$NEW_IP"; then
    echo "IP inválido: $NEW_IP"
    exit 1
fi

OLD_LAB=""
if [ -f "$STATE_FILE" ]; then
    OLD_LAB=$(tr -d '[:space:]' < "$STATE_FILE")
fi

if [ ! -f "$CONF_FILE" ]; then
    echo "Arquivo ausente: $CONF_FILE"
    exit 1
fi

mapfile -t KEPT < <(grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' "$CONF_FILE" | grep -vx "$OLD_LAB" | grep -vx "$NEW_IP" || true)
if [ "${#KEPT[@]}" -eq 0 ]; then
    echo "Nenhum outro IP restaria em $CONF_FILE. Abortado para não apagar a estação fixa."
    exit 1
fi

{
    echo "# IPv4 da estação de trabalho. Não apague estas linhas ao atualizar o laboratório."
    echo "# Atualizado em $(date -Iseconds)"
    for ip in "${KEPT[@]}"; do
        echo "$ip"
    done
    echo
    echo "# Laboratório TimeFlow. IP público; o Wi-Fi local não é usado aqui."
    echo "# Troque com: /root/dbadmin/atualizar-ip-laboratorio.sh NOVO.IP.PUBLICO"
    echo "$NEW_IP"
} > "$CONF_FILE"

echo "$NEW_IP" > "$STATE_FILE"
echo "Laboratório: ${OLD_LAB:-"(nenhum)"} → $NEW_IP"
echo "Estações mantidas: ${KEPT[*]}"

set +e
"$RESTRICT"
restrict_status=$?
set -e
if [ "$restrict_status" -ne 0 ]; then
    echo "restrict-db-ports.sh retornou $restrict_status. Conferindo a cadeia do Docker."
fi

if ! iptables -L ADS_DB_PORTS -n | grep -q "$NEW_IP"; then
    echo "O IP $NEW_IP não entrou em ADS_DB_PORTS."
    exit 1
fi

if [ -n "$OLD_LAB" ] && [ "$OLD_LAB" != "$NEW_IP" ]; then
    remove_ufw_ip "$OLD_LAB"
fi
allow_ufw_ip "$NEW_IP"

echo
echo "OK. A porta 5432 aceita o laboratório $NEW_IP (com senha)."
echo "Estações que continuam liberadas: ${KEPT[*]}"

if [ -z "${DBADMIN_FROM_PANEL:-}" ] && systemctl is-active --quiet dbadmin-panel.service; then
    systemctl restart dbadmin-panel.service
    echo "Painel da VPS: acesso da porta 8448 atualizado para $NEW_IP."
fi
