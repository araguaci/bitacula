#!/usr/bin/env bash
# Backup de todos os bancos dos containers PostgreSQL em execução.
#
# Uso manual:
#   sudo /root/dbadmin/backup-postgres.sh
#   sudo /root/dbadmin/backup-postgres.sh --keep 30
#   sudo /root/dbadmin/backup-databases.sh --postgres
#   sudo /root/dbadmin/backup-databases.sh --mysql
#   sudo /root/dbadmin/backup-databases.sh --postgres --mysql
#
# Rotina diária (cron), às 02:15, guardando 14 cópias:
#   15 2 * * * /root/dbadmin/backup-postgres.sh --keep 14 >> /root/dbadmin/backups/backup.log 2>&1
#
# Cada execução cria /root/dbadmin/backups/AAAAMMDD-HHMMSS/<container>/*.dump
# Formato: pg_dump -Fc. Papéis e tablespaces: globals.sql

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_ROOT="${ROOT}/backups"
LOCK_FILE="${DEST_ROOT}/.lock"
KEEP=14
DEST_OVERRIDE=""
NO_LOCK=0
APPEND_MANIFEST=0

usage() {
    cat <<'EOF'
Uso:
  sudo /root/dbadmin/backup-postgres.sh [--keep N]
  sudo /root/dbadmin/backup-postgres.sh --dest PASTA --no-lock --append-manifest

  --keep N   quantas pastas de backup conservar (padrão: 14).
             Use --keep 0 para não apagar nenhuma.
  --dest     grava nesta pasta, sem criar outra e sem apagar antigas.
  --no-lock  quem chamou já segurou o lock.
  --append-manifest
             acrescenta ao MANIFEST.txt em vez de recomeçar o arquivo.
EOF
    exit 0
}

log() {
    echo "$(date -Iseconds) $*"
}

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage ;;
        --keep)
            shift
            KEEP="${1:-}"
            ;;
        --keep=*)
            KEEP="${1#--keep=}"
            ;;
        --dest)
            shift
            DEST_OVERRIDE="${1:-}"
            ;;
        --dest=*)
            DEST_OVERRIDE="${1#--dest=}"
            ;;
        --no-lock)
            NO_LOCK=1
            ;;
        --append-manifest)
            APPEND_MANIFEST=1
            ;;
        *)
            echo "Opção desconhecida: $1"
            exit 1
            ;;
    esac
    shift
done

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
if [ "$NO_LOCK" -eq 0 ]; then
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        log "backup já em execução; saindo"
        exit 0
    fi
fi

detect_user() {
    local container=$1
    local from_env user
    from_env=$(docker inspect "$container" --format '{{range .Config.Env}}{{println .}}{{end}}' \
        | sed -n 's/^POSTGRES_USER=//p' | head -1)
    for user in $from_env postgres admin; do
        [ -z "$user" ] && continue
        if docker exec "$container" psql -U "$user" -d postgres -Atqc 'SELECT 1' >/dev/null 2>&1; then
            echo "$user"
            return 0
        fi
    done
    return 1
}

if [ -n "$DEST_OVERRIDE" ]; then
    DEST="$DEST_OVERRIDE"
    if [ ! -d "$DEST" ]; then
        echo "Pasta inexistente: $DEST"
        exit 1
    fi
else
    STAMP=$(date +%Y%m%d-%H%M%S)
    DEST="${DEST_ROOT}/${STAMP}"
    mkdir -p "$DEST"
    chmod 700 "$DEST"
fi
FAILED=0
SUMMARY="${DEST}/MANIFEST.txt"

mapfile -t CONTAINERS < <(docker ps --format '{{.Names}} {{.Image}}' | awk 'tolower($2) ~ /postgres/ {print $1}')
if [ "${#CONTAINERS[@]}" -eq 0 ]; then
    log "nenhum container PostgreSQL em execução"
    if [ "$APPEND_MANIFEST" -eq 1 ]; then
        echo "Nenhum container PostgreSQL em execução" >> "$SUMMARY"
    else
        echo "nenhum container" > "$SUMMARY"
    fi
    exit 1
fi

log "início em $DEST"
if [ "$APPEND_MANIFEST" -eq 1 ]; then
    {
        echo
        echo "PostgreSQL"
        echo "Formato dos bancos: pg_dump -Fc. Papéis: globals.sql"
        echo
    } >> "$SUMMARY"
else
    {
        echo "Backup PostgreSQL"
        echo "Quando: $(date -Iseconds)"
        echo "Pasta: $DEST"
        echo
        echo "Formato dos bancos: pg_dump -Fc. Papéis: globals.sql"
        echo
    } > "$SUMMARY"
fi

for container in "${CONTAINERS[@]}"; do
    out="${DEST}/${container}"
    mkdir -p "$out"
    chmod 700 "$out"
    if ! user=$(detect_user "$container"); then
        log "FALHA $container: nenhum usuário conseguiu conectar"
        echo "FALHA $container sem usuário" >> "$SUMMARY"
        FAILED=1
        continue
    fi
    log "container $container usuário $user"
    echo "Instância $container (usuário $user): $out" >> "$SUMMARY"

    if ! docker exec "$container" pg_dumpall -U "$user" --globals-only > "$out/globals.sql"; then
        log "FALHA $container: globals"
        echo "FALHA globals $container" >> "$SUMMARY"
        FAILED=1
        continue
    fi
    chmod 600 "$out/globals.sql"

    if ! mapfile -t DBS < <(docker exec "$container" psql -U "$user" -d postgres -Atqc \
        "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY 1"); then
        log "FALHA $container: listar bancos"
        echo "FALHA listar $container" >> "$SUMMARY"
        FAILED=1
        continue
    fi
    for db in "${DBS[@]}"; do
        [ -z "$db" ] && continue
        target="${out}/${db}.dump"
        if docker exec "$container" pg_dump -U "$user" -d "$db" -Fc > "$target" && [ -s "$target" ]; then
            chmod 600 "$target"
            log "ok $container/$db"
        else
            rm -f "$target"
            log "FALHA $container/$db"
            echo "FALHA $container/$db" >> "$SUMMARY"
            FAILED=1
        fi
    done
done

{
    echo
    echo "Restaurar um banco:"
    echo "  docker exec -i CONTAINER pg_restore -U USUARIO -d NOME --clean --if-exists -"
    echo "  (a entrada desse comando é o arquivo CONTAINER/NOME.dump desta pasta)"
    echo
    echo "Arquivos:"
} >> "$SUMMARY"
find "$DEST" -type f -exec stat -c '%s %n' {} + | sort -k2 >> "$SUMMARY"
chmod 600 "$SUMMARY"

if [ -z "$DEST_OVERRIDE" ] && [ "$KEEP" -gt 0 ]; then
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
