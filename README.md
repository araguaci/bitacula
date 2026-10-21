# Bitácula

## 🛡️ Sentinel Status
- **Status:** 🟡 MVP / Em Desenvolvimento
- **Tier:** B
- **Health:** 50% / **ROI Potencial:** TBD
- **Stack:** Python 3.11, Bash, nginx, UFW, Docker, PostgreSQL, MySQL, Redis

---

Diário de bordo de uma VPS. O nome vem do livro em que o oficial de quarto anota o estado do navio: o que está no ar, quem pode entrar e o que já foi copiado para o caso de precisar voltar.

**English.** Bitácula is a local ship's log for a VPS: a small admin panel, laboratory IP allowlists for database ports, and PostgreSQL and MySQL backups. It stays off the public internet except for the addresses you list.

As telas, com dados de exemplo, estão no [guia](docs/GUIA.md). Dá para ver o painel sem instalar.

[Contribuir](CONTRIBUTING.md) · [Conduta](CODE_OF_CONDUCT.md) · [Segurança](SECURITY.md) · [Changelog](CHANGELOG.md) · [Licença MIT](LICENSE)

## O que ela faz

- Mostra CPU, memória, disco e containers.
- Lista PostgreSQL, MySQL e Redis, com tamanho, sem mostrar senha de banco.
- Abre o painel só para os IPs autorizados, com usuário e senha.
- Troca o IP público do laboratório nas portas 3306, 6379 e 5432 sem apagar a outra estação.
- Gera backup de PostgreSQL, de MySQL, ou dos dois, na mesma pasta.

## O que ela não faz

- Não publica o relatório na internet.
- Não guarda senha de banco no git, no manifesto nem na tela.
- Não substitui o firewall da máquina. Ela escreve regras em cima do que você já confia.

## Requisitos

| Obrigatório | Para o painel e os backups |
|-------------|----------------------------|
| Python 3.11+, Bash 4+ | Docker com os containers em execução |
| OpenSSL, nginx, UFW | `mysqldump` dentro da imagem MySQL e `pg_dump` na imagem PostgreSQL |

## Instalação

```bash
git clone https://github.com/araguaci/bitacula.git
cd bitacula
sudo python3 panel/server.py
```

Na primeira subida o painel cria `panel/CREDENCIAIS.txt` com usuário e senha, só nesta máquina. Esse arquivo está no `.gitignore`.

O processo escuta em `127.0.0.1:8787`. O nginx publica a porta `8448` em HTTPS e recusa qualquer origem que não esteja na lista de estações. O navegador avisa do certificado local na primeira visita.

Unidade de exemplo: [deploy/bitacula-panel.service](deploy/bitacula-panel.service). Ajuste o caminho do clone antes de instalar.

## Configuração

| Variável | Uso |
|----------|-----|
| `BITACULA_PUBLIC_IP` | IP que aparece no painel e no certificado. Sem ela, a Bitácula escolhe o primeiro IPv4 público da máquina. |
| `BITACULA_IP_CONF` | Arquivo com um IPv4 por linha. Modelo em [examples/workstations.conf](examples/workstations.conf). |
| `BITACULA_NGINX_SITE` | Caminho do site nginx gerado. |
| `BITACULA_NGINX_LINK` | Symlink em `sites-enabled`. |

Se `/etc/artesdosul/workstation-ip.conf` já existir, ele continua valendo. Numa máquina nova, use `/etc/bitacula/workstations.conf`.

O IP atual do laboratório fica em `laboratorio.ip`, ao lado dos scripts. Há um modelo em [laboratorio.ip.example](laboratorio.ip.example). Os endereços de exemplo são da faixa de documentação (RFC 5737).

## Backup

```bash
sudo ./backup-databases.sh --postgres
sudo ./backup-databases.sh --mysql
sudo ./backup-databases.sh --postgres --mysql --keep 14
```

Cada execução cria `backups/AAAAMMDD-HHMMSS/`. PostgreSQL sai em `pg_dump -Fc`. MySQL sai em `mysqldump` comprimido, mais `grants.sql`. A pasta `backups/` não entra no git.

No painel, a seção **Backups** oferece as três opções.

Para restaurar, o caminho está no `MANIFEST.txt` da pasta. A senha usada na restauração é a do próprio container, não a do painel.

## IP do laboratório

Quando a rede do laboratório muda o IP público:

```bash
curl -4 ifconfig.me
sudo ./atualizar-ip-laboratorio.sh 203.0.113.10
```

O comando troca só o IP do laboratório. A estação fixa permanece. O mesmo formulário existe no painel, em **Acesso**.

O endereço da rede local do laboratório não chega até a VPS. Use o IP público.

## Verificação

```bash
python3 -m py_compile panel/server.py
bash -n backup-databases.sh backup-mysql.sh backup-postgres.sh atualizar-ip-laboratorio.sh
```

O mesmo roda em cada push, no workflow `Verificar`.

## Comunidade

- Ideia ou falha: [issue](https://github.com/araguaci/bitacula/issues/new/choose).
- Correção: pull request, com o modelo do repositório.
- Vulnerabilidade: [SECURITY.md](SECURITY.md), por e-mail, antes de qualquer issue pública.
- Conduta: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Prompt da imagem hero

Capa do artigo em `artigos/bitacula-hero.webp`, 1200×675. As telas do guia são capturas da interface, em `docs/img/`.

```
Hero image para artigo X.com "Trocar o IP sem apagar a outra estação".
Dimensões exatas: 1200×675 pixels (16:9, share card / preview do artigo).
Composição: bloco editorial central com o título "Trocar o IP sem apagar a outra estação" em destaque;
subtítulo menor "Bitácula · diário de bordo".
Conteúdo importante centrado, margens seguras para recorte em feed/preview.
Tema visual: livro de quarto náutico aberto sobre uma mesa escura, duas linhas de endereço IP em tipografia mono, uma riscada e substituída, a outra intacta. Sem rostos.
Paleta: tinta #121510, papel #f3f1e6, âmbar #e2a23a, musgo #8fbf6a.
Estilo: documentário investigativo, data journalism, tipografia editorial bold, serifada.
Grain sutil, sem fundo branco flat, sem emoji, sem clipart.
```

## Licença

[MIT](LICENSE). Copyright (c) 2026 araguaci.
