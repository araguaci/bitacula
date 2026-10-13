#!/usr/bin/env bash
# Gera backup de PostgreSQL, MySQL ou dos dois, na mesma pasta.
#
# Uso:
#   sudo /root/dbadmin/backup-databases.sh --postgres
#   sudo /root/dbadmin/backup-databases.sh --mysql
#   sudo /root/dbadmin/backup-databases.sh --postgres --mysql
#   sudo /root/dbadmin/backup-databases.sh --postgres --mysql --keep 14

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_ROOT="${ROOT}/backups"
LOCK_FILE="${DEST_ROOT}/.lock"
KEEP=14
DO_POSTGRES=0
DO_MYSQL=0

usage() {
    cat <<'EOF'
Uso:
  sudo /root/dbadmin/backup-databases.sh --postgres
  sudo /root/dbadmin/backup-databases.sh --mysql
  sudo /root/dbadmin/backup-databases.sh --postgres --mysql [--keep N]

  --postgres   copia os containers PostgreSQL
  --mysql      copia os containers MySQL
  --keep N     quantas pastas conservar (padrão: 14). 0 não apaga nenhuma.
EOF
    exit 0
}

log() {
    echo "$(date -Iseconds) $*"
}

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage ;;
        --postgres) DO_POSTGRES=1 ;;
        --mysql) DO_MYSQL=1 ;;
        --keep)
            shift
            KEEP="${1:-}"
            ;;
        --keep=*)
            KEEP="${1#--keep=}"
            ;;
        *)
            echo "Opção desconhecida: $1"
            exit 1
            ;;
    esac
    shift
done

if [ "$DO_POSTGRES" -eq 0 ] && [ "$DO_MYSQL" -eq 0 ]; then
    echo "Escolha --postgres, --mysql ou os dois."
    exit 1
fi

if ! [[ "$KEEP" =~ ^[0-9]+$ ]]; then
    echo "--keep precisa ser um número inteiro"
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "Execute como root."
    exit 1
fi

mkdir -p "$DEST_ROOT"
chmod 700 "$DEST_ROOT"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "backup já em execução; saindo"
    exit 0
fi

STAMP=$(date +%Y%m%d-%H%M%S)
DEST="${DEST_ROOT}/${STAMP}"
mkdir -p "$DEST"
chmod 700 "$DEST"
SUMMARY="${DEST}/MANIFEST.txt"

if [ "$DO_POSTGRES" -eq 1 ] && [ "$DO_MYSQL" -eq 1 ]; then
    TITLE="Backup PostgreSQL e MySQL"
    MOTORS="PostgreSQL, MySQL"
elif [ "$DO_POSTGRES" -eq 1 ]; then
    TITLE="Backup PostgreSQL"
    MOTORS="PostgreSQL"
else
    TITLE="Backup MySQL"
    MOTORS="MySQL"
fi

{
    echo "$TITLE"
    echo "Quando: $(date -Iseconds)"
    echo "Pasta: $DEST"
    echo "Motores: $MOTORS"
    echo
} > "$SUMMARY"
chmod 600 "$SUMMARY"

log "início $TITLE em $DEST"
FAILED=0

if [ "$DO_POSTGRES" -eq 1 ]; then
    if ! "$ROOT/backup-postgres.sh" --dest "$DEST" --no-lock --append-manifest --keep 0; then
        log "PostgreSQL terminou com falha"
        FAILED=1
    fi
fi

if [ "$DO_MYSQL" -eq 1 ]; then
    if ! "$ROOT/backup-mysql.sh" --dest "$DEST" --no-lock --append-manifest --keep 0; then
        log "MySQL terminou com falha"
        FAILED=1
    fi
fi

if [ "$KEEP" -gt 0 ]; then
    mapfile -t OLD < <(find "$DEST_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
    count=${#OLD[@]}
    if [ "$count" -gt "$KEEP" ]; then
        remove=$((count - KEEP))
        for name in "${OLD[@]:0:remove}"; do
            log "apagando backup antigo $name"
            rm -rf "${DEST_ROOT}/${name}"
        done
    fi
fi

if [ "$FAILED" -ne 0 ]; then
    log "terminou com falhas: $DEST"
    exit 1
fi

log "terminou ok: $DEST"
