# DraftBot

Assistente de seleção de campeões do League of Legends (todas as rotas). Lê a seleção e a conta logada pela
API local do cliente (LCU), busca estatísticas do patch atual na API pública da OP.GG e mostra recomendações,
o pool do jogador, runas e build numa página local (`http://127.0.0.1:8765`).

> Repositório **privado**. Os amigos recebem só o `.zip` do executável, por um link "qualquer pessoa com o link".

## Estrutura

| Arquivo | O que é |
|---|---|
| `draftbot.py` | Programa local: cliente do LoL, OP.GG, cache, servidor da página. Só biblioteca padrão do Python. |
| `index.html` | A página (interface e cálculo das recomendações). |
| `Iniciar DraftBot.bat` | Roda a partir do código-fonte (baixa um Python portátil se o PC não tiver). |
| `LEIA-ME.txt` / `LEIA-ME-EXE.txt` | Guia de uso (código-fonte / executável). O segundo vai dentro do `.zip`. |
| `CHANGELOG.md` | Notas de cada versão — usadas na release e no aviso de atualização. |
| `assets/draftbot.ico` | Ícone do executável. |
| `tests/` | Testes automáticos, com o cliente do LoL e a OP.GG simulados e dados reais da OP.GG em `fixtures/`. |
| `tools/` | `check_version.py` (tag × versão × changelog), `release_notes.py` e `gist_json.py` (monta o `version.json`). |
| `.github/workflows/` | `build.yml` (testes + `.exe` + release) e `avisar.yml` (aviso de nova versão). |

## Rodar e testar

```bash
python draftbot.py                                  # abre a página
python -m unittest discover -s tests -t . -v        # testes do programa
node tests/test_page.mjs                            # testes da página
python draftbot.py --selftest                       # autoteste (o mesmo que roda no .exe gerado)
```

## Publicar uma versão nova

1. Mude `VERSION` em `draftbot.py` e escreva a seção `## vX.Y.Z` no `CHANGELOG.md`.
2. Envie para o GitHub e crie a release `vX.Y.Z` (aba **Releases → Draft a new release**, tag nova a partir de `main`),
   ou `git tag vX.Y.Z && git push --tags`.
3. O GitHub roda os testes (Linux e Windows), gera o `DraftBot.exe` com Nuitka, confere se ele abre
   (`--selftest`) e anexa `DraftBot-vX.Y.Z-windows.zip` à release. As notas da release trazem o
   `version.json` pronto, já com a impressão digital (`sha256`) do zip.
4. Baixe o `.zip` da release e, no Google Drive, **substitua** o arquivo (botão direito → Gerenciar versões →
   Enviar nova versão). Assim o link continua o mesmo.
5. Edite o `version.json` do gist colando o bloco das notas da release (com o link do Drive),
   ou rode **Actions → Avisar nova versão**. Quem tem o DraftBot vê o aviso com **Atualizar agora**.

A atualização automática só instala se o `sha256` do gist bater com o arquivo baixado; sem ele, o aviso
mostra só o link. O link precisa ser público ("qualquer pessoa com o link").

## Configuração única

- **Repositório**: privado.
- **Gist secreto** (não listado; só quem tem o link vê) com um arquivo `version.json`:
  `{"version": "0.0.0", "url": "", "notes": "", "sha256": ""}`
- Em **Settings → Secrets and variables → Actions**:
  - variável `UPDATE_URL` = endereço *raw* do gist, sem o código da revisão:
    `https://gist.githubusercontent.com/<usuário>/<id do gist>/raw/version.json` (vai embutido no `.exe`)
  - variável `GIST_ID` = `<id do gist>`
  - variável `DOWNLOAD_URL` = o link que você manda para os amigos
  - secret `GIST_TOKEN` = token do GitHub com permissão **gist** (só gist)

## Observações

- O `.exe` não tem assinatura digital; o Windows/antivírus podem alertar nas primeiras vezes (explicado no LEIA-ME).
- No `.exe`, cache e registro ficam em `%LOCALAPPDATA%\DraftBot`; no código-fonte, ao lado do `draftbot.py`.
- O programa só lê a seleção; nunca bane, escolhe ou trava campeões.
