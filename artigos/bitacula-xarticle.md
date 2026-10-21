# Trocar o IP sem apagar a outra estação

Quando a operadora muda o IP público do laboratório, o reflexo é abrir o firewall e colar o endereço novo por cima do antigo. Se a regra era uma linha só, a outra estação sai junto. Eu queria anotar o estado da VPS e trocar só o laboratório.

A Bitácula é esse livro de quarto. Mostra CPU, memória, disco e containers. Lista PostgreSQL, MySQL e Redis com tamanho. A senha de banco não entra na tela. O painel escuta em `127.0.0.1:8787`. O nginx publica a porta `8448` e recusa origem que não esteja na lista.

## A senha que a tela não mostra

Na primeira subida o painel grava `panel/CREDENCIAIS.txt`, só naquela máquina. O arquivo fica fora do git. Dali sai o usuário e a senha desta interface.

O banco é outra história. O painel diz o usuário, o host, a porta e o tamanho. A senha continua no container. Quem restaura uma cópia usa essa senha, a do container.

> A senha usada na restauração é a do próprio container, não a do painel.

## Duas estações na mesma porta

As portas são 3306, 6379 e 5432. O comando troca o IP do laboratório. A estação fixa continua na lista.

O endereço da rede local do laboratório não chega até a VPS. O que entra na regra é o IP público, o mesmo que `curl -4 ifconfig.me` devolve lá.

Na amostra do guia, `203.0.113.10` é o laboratório e `198.51.100.24` é a estação que permanece. Os dois são da faixa de documentação da RFC 5737. Não são desta máquina.

## A cópia fica na pasta

Dá para gerar backup de PostgreSQL, de MySQL, ou dos dois. Cada execução cria `backups/AAAAMMDD-HHMMSS/`. Postgres sai em `pg_dump -Fc`. MySQL sai comprimido, com `grants.sql`. A pasta não entra no git. O caminho de restauração está no `MANIFEST.txt`.

## Dá para ver sem instalar

O repositório tem as telas. Usuário, bancos e endereços dessa captura são de exemplo. A interface é a mesma: entrada, visão geral, bancos, containers, acesso e backups.

O painel não substitui o firewall. Ele escreve regra em cima do que você já confia. Eu não publicaria a porta 8448 na internet aberta.

## Comece

```bash
git clone https://github.com/araguaci/bitacula.git
cd bitacula
sudo python3 panel/server.py
```

Código: [github.com/araguaci/bitacula](https://github.com/araguaci/bitacula)

Guia com as telas: [github.com/araguaci/bitacula/blob/main/docs/GUIA.md](https://github.com/araguaci/bitacula/blob/main/docs/GUIA.md)

Texto no portfólio: [artesdosul.com/devops/bitacula](https://artesdosul.com/devops/bitacula/)

## Fontes

- IETF, [RFC 5737](https://www.rfc-editor.org/rfc/rfc5737), IPv4 Address Blocks Reserved for Documentation (2010)
- Bitácula 0.1.0, README e painel (2026)
