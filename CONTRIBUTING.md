# Como contribuir

Obrigado por chegar até aqui. A Bitácula é um diário de bordo de VPS: painel local, acesso do laboratório e backup de PostgreSQL e MySQL. Contribuições são bem-vindas quando deixam o projeto mais claro e mais seguro.

Leia também o [Código de Conduta](CODE_OF_CONDUCT.md) e a [política de segurança](SECURITY.md).

## Antes de abrir uma issue

- Procure se o assunto já existe.
- Falha de segurança: e-mail para araguaci@gmail.com. Não descreva o abuso numa issue aberta.
- Diga o que você esperava, o que aconteceu e a versão do sistema.

## Antes de abrir um pull request

1. Faça um fork e um branch a partir de `main`.
2. Mantenha a mudança pequena e com um propósito só.
3. Escreva para quem vai operar o servidor: português claro na interface e nos textos de ajuda.
4. Não inclua senha, dump, IP real de produção, certificado ou `auth.json`.
5. Rode a verificação local:

```bash
python3 -m py_compile panel/server.py
bash -n backup-databases.sh backup-mysql.sh backup-postgres.sh atualizar-ip-laboratorio.sh
```

## Estilo

- Python 3.11+ e Bash com `set -euo pipefail`.
- Caminho do projeto vem do próprio script, não de um diretório fixo de uma máquina.
- Endereço de exemplo só da faixa de documentação: `203.0.113.0/24` e `198.51.100.0/24`.
- O painel não mostra senha de banco. Um pull request que passe a mostrar precisa ser recusado.

## Mensagem de commit

Uma frase que diga por que a mudança existe. Exemplos:

```text
Permite escolher o motor do backup para não copiar o que não mudou.

Avisa quando o IP do laboratório sai da allowlist.
```

## Revisão

Quem mantém o repositório lê o diff, pede ajuste se faltar teste ou texto, e faz o merge em `main`. Correção de segurança pode entrar fora dessa fila.
