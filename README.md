# DraftBot

Assistente de seleção de campeões do League of Legends (todas as rotas). Lê a seleção e a conta logada pela
API local do cliente (LCU), busca estatísticas do patch atual na API pública da OP.GG e mostra recomendações,
o pool do jogador, runas e build numa página local (`http://127.0.0.1:8765`).

> Repositório público. Os amigos baixam o `.zip` na página da última release.

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
| `tools/` | `check_version.py` (tag × versão × changelog), `release_notes.py` e `e2e_update.py` (teste da atualização). |
| `.github/workflows/` | `build.yml` (testes + `.exe` + release). |

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
3. O GitHub roda os testes (Linux e Windows), gera o `DraftBot.exe` com Nuitka, confere se ele abre (`--selftest`),
   testa a atualização automática com o `.exe` de verdade e anexa `DraftBot-vX.Y.Z-windows.zip` à release.

Pronto: quem tem o DraftBot vê o aviso com **Atualizar agora** em até uma hora. O programa consulta
`api.github.com/repos/<repo>/releases/latest` e só instala se o `.zip` baixado tiver a mesma impressão
digital (sha256) que o GitHub informa para ele.

Para mandar o DraftBot a alguém: `https://github.com/<usuário>/draftbot/releases/latest`.

## Observações

- O `.exe` não tem assinatura digital; o Windows/antivírus podem alertar nas primeiras vezes (explicado no LEIA-ME).
- No `.exe`, cache e registro ficam em `%LOCALAPPDATA%\DraftBot`; no código-fonte, ao lado do `draftbot.py`.
- O programa só lê a seleção; nunca bane, escolhe ou trava campeões.
