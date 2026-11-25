# Sincronização automática de workflows no Linux

A instalação pessoal usava uma lista fixa no `config.yaml`. O utilitário
`tools/sync_github_workflows.py` consulta os repositórios próprios da conta
Marcelo7889 e acrescenta seus workflows ativos ao Actions Monitor. Ele também
descobre novos workflows em repositórios existentes. Repositórios arquivados ou
desabilitados são ignorados; projetos sem workflows aparecem quando um workflow
ativo for disponibilizado pela API do GitHub.

A sincronização roda no início da sessão e a cada cinco minutos por um timer
systemd do usuário, mesmo com a janela do monitor fechada. O monitor lê a
configuração atualizada pelo seu mecanismo de recarga, a cada cinco segundos.
Não exige recompilar o aplicativo e não altera nada no GitHub.

Usa o token que já existe na configuração, sem copiá-lo para scripts ou unidades.
O token precisa alcançar os repositórios e ter leitura de Actions. Novos
workflows consultam seus status a cada 60 segundos. As entradas existentes,
preferências de notificação, comentários e credenciais são preservados.
O utilitário apenas acrescenta entradas: remover manualmente um workflow ativo
faz com que ele reapareça no próximo ciclo. Para suspender essa descoberta, pare
o timer antes de editar a lista.

Antes da primeira gravação, salva uma cópia privada em
`~/.local/opt/ActionsMonitor-linux/config.yaml.before-autodiscovery`.
Não apaga cadastros antigos. Falha de API, token inválido ou edição concorrente
impede a gravação daquele ciclo; o timer tenta novamente depois. Não altera o
arquivo se não houver novidades. Não grava dados parciais de uma descoberta.

O código instalado fica em `~/.local/share/actionsmonitor-sync/` e as unidades em
`~/.config/systemd/user/`. Dependências: Python 3, requests e PyYAML.

```bash
# Simular, sem gravar:
python3 tools/sync_github_workflows.py --config ~/.local/opt/ActionsMonitor-linux/config.yaml --owner Marcelo7889

# Consultar execução e agenda:
systemctl --user status actionsmonitor-sync.timer actionsmonitor-sync.service
journalctl --user -u actionsmonitor-sync.service -n 20 --no-pager

# Executar imediatamente:
systemctl --user start actionsmonitor-sync.service

# Desativar (mantém workflows já cadastrados):
systemctl --user disable --now actionsmonitor-sync.timer

# Testes sem rede nem credenciais:
python3 -m unittest discover -s tests -p test_sync_github_workflows.py -v
```

API usada: [repositórios autenticados](https://docs.github.com/en/rest/repos/repos#list-repositories-for-the-authenticated-user)
e [workflows do repositório](https://docs.github.com/en/rest/actions/workflows#list-repository-workflows).
