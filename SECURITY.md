# Política de segurança

A Bitácula administra uma VPS, abre portas de banco e guarda cópias do PostgreSQL e do MySQL. Um defeito aqui pode expor dados. Reporte em particular, antes de abrir uma issue pública.

## O que entra neste canal

- Falha que permita entrar no painel sem a senha, ou a partir de um IP que não está na lista.
- Vazamento de senha de banco, de sessão, de certificado ou do arquivo de credenciais.
- Backup que grave segredo em log, manifesto ou nome de arquivo.
- Forma de furar o `deny all` do nginx ou a allowlist do firewall.

## O que não entra

- Dúvida de uso, pedido de função ou erro sem impacto de segurança. Abra uma issue.
- Ausência de certificado público no navegador na primeira visita. O painel usa um certificado local de propósito.

## Como reportar

Escreva para araguaci@gmail.com com o assunto **Bitácula — segurança**.

Inclua:

1. Versão ou commit.
2. O que você fez e o que aconteceu.
3. O impacto que você enxerga.
4. Se você já tem um jeito de reproduzir, os passos, sem colar senha, dump ou conteúdo de banco.

Não abra issue pública, pull request ou discussão com o detalhe do problema até haver uma correção ou um acordo de divulgação.

## Prazo

Há uma resposta inicial em até 7 dias. Se o relato for procedente, a correção sai numa versão seguinte, com menção no CHANGELOG sem o passo a passo do abuso.
