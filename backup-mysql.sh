#!/usr/bin/env bash
# Backup de todos os bancos de aplicação dos containers MySQL em execução.
#
# Uso manual:
#   sudo /root/dbadmin/backup-mysql.sh
#   sudo /root/dbadmin/backup-mysql.sh --keep 14
#   sudo /root/dbadmin/backup-databases.sh --mysql
#
# Cada execução cria /root/dbadmin/backups/AAAAMMDD-HHMMSS/<container>/*.sql.gz
# Também grava grants.sql com os SHOW GRANTS. A senha do container não entra no arquivo.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_ROOT="${ROOT}/backups"
LOCK_FILE="${DEST_ROOT}/.lock"
KEEP=14
DEST_OVERRIDE=""
NO_LOCK=0
APPEND_MANIFEST=0
SKIP_DBS="information_schema performance_schema sys mysql"

usage() {
    cat <<'EOF'
Uso:
  sudo /root/dbadmin/backup-mysql.sh [--keep N]
  sudo /root/dbadmin/backup-mysql.sh --dest PASTA --no-lock --append-manifest

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

mapfile -t CONTAINERS < <(docker ps --format '{{.Names}} {{.Image}}' | awk 'tolower($2) ~ /mysql/ {print $1}')
if [ "${#CONTAINERS[@]}" -eq 0 ]; then
    log "nenhum container MySQL em execução"
    if [ "$APPEND_MANIFEST" -eq 1 ]; then
        echo "Nenhum container MySQL em execução" >> "$SUMMARY"
    else
        echo "nenhum container" > "$SUMMARY"
    fi
    exit 1
fi

log "início em $DEST"
if [ "$APPEND_MANIFEST" -eq 1 ]; then
    {
        echo
        echo "MySQL"
        echo "Formato dos bancos: mysqldump | gzip. Contas: grants.sql"
        echo
    } >> "$SUMMARY"
else
    {
        echo "Backup MySQL"
        echo "Quando: $(date -Iseconds)"
        echo "Pasta: $DEST"
        echo
        echo "Formato dos bancos: mysqldump | gzip. Contas: grants.sql"
        echo
    } > "$SUMMARY"
fi

safe_name() {
    [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$ ]]
}

skip_db() {
    local db=$1
    local item
    for item in $SKIP_DBS; do
        [ "$db" = "$item" ] && return 0
    done
    return 1
}

for container in "${CONTAINERS[@]}"; do
    if ! safe_name "$container"; then
        log "FALHA nome de container rejeitado"
        echo "FALHA container com nome inválido" >> "$SUMMARY"
        FAILED=1
        continue
    fi
    out="${DEST}/${container}"
    mkdir -p "$out"
    chmod 700 "$out"
    log "container $container"
    echo "Instância $container: $out" >> "$SUMMARY"

    grants="${out}/grants.sql"
    if docker exec "$container" sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --batch --raw -N -e "SELECT CONCAT(\"SHOW GRANTS FOR \", QUOTE(user), \"@\", QUOTE(host), \";\") FROM mysql.user"' >"$grants"; then
        chmod 600 "$grants"
        log "ok $container/grants"
    else
        rm -f "$grants"
        log "FALHA $container/grants"
        echo "FALHA $container/grants" >> "$SUMMARY"
        FAILED=1
    fi

    if ! mapfile -t DBS < <(docker exec "$container" sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e "SHOW DATABASES"'); then
        log "FALHA $container: listar bancos"
        echo "FALHA listar $container" >> "$SUMMARY"
        FAILED=1
        continue
    fi
    for db in "${DBS[@]}"; do
        [ -z "$db" ] && continue
        if skip_db "$db"; then
            continue
        fi
        if ! [[ "$db" =~ ^[A-Za-z0-9_]+$ ]]; then
            log "FALHA $container/$db nome rejeitado"
            echo "FALHA $container/$db nome" >> "$SUMMARY"
            FAILED=1
            continue
        fi
        target="${out}/${db}.sql.gz"
        if docker exec "$container" sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers --events --set-gtid-purged=OFF --default-character-set=utf8mb4 --databases "$1"' sh "$db" | gzip -c >"$target" && [ -s "$target" ]; then
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
    echo "Restaurar um banco MySQL:"
    echo "  gunzip -c CONTAINER/NOME.sql.gz | docker exec -i CONTAINER sh -c 'mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\"'"
    echo
    echo "Arquivos MySQL:"
} >> "$SUMMARY"
find "$DEST" -type f \( -name '*.sql.gz' -o -name 'grants.sql' \) -exec stat -c '%s %n' {} + | sort -k2 >> "$SUMMARY"
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
