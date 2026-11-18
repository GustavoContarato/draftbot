# Mudanças

## v2.5.3
- Corrigido: campeões com poucas partidas de confronto (comum logo após um patch) apareciam como "Seguro às cegas" só porque os counters ainda não tinham aparecido nos dados. Agora o risco deles é estimado pelo típico da rota até haver partidas suficientes.
- Aviso quando o patch saiu há pouco e ainda há poucas partidas.

## v2.5.2
- Corrigido: em alguns PCs a 2.5.1 abria a janela com "This page isn't working" (pasta interna incompleta). Agora o programa se prepara do zero a cada abertura.
- Se faltar algum arquivo do programa, a janela explica o que fazer em vez de ficar em branco.

## v2.5.1
- Pasta organizada: o DraftBot agora é um único arquivo (DraftBot.exe), junto só do LEIA-ME.

## v2.5.0
- Atualização automática: o aviso de versão nova ganhou o botão "Atualizar agora", que baixa, confere e instala a versão nova e reabre o DraftBot. Se algo falhar, continua na versão anterior.

## v2.4.0
- Dia de patch novo: nas primeiras 24 h as estatísticas também usam as partidas do patch anterior, com peso que cai até zero ao fim do dia. A página avisa enquanto a mistura está ativa.

## v2.3.0
- O DraftBot agora abre na janela dele, como um aplicativo: sem abas, sem barra de endereço e sem a janela preta. Fechar a janela encerra o programa.
- A página continua atualizando mesmo com a janela minimizada.
- Ícone do DraftBot na janela.

## v2.2.0
- Agora também como executável (DraftBot.exe): não precisa de Python.
- Corrigido: uma falha momentânea ao buscar estatísticas ficava valendo até fechar a página; agora tenta de novo após 1 minuto.
- Corrigido: com o app aberto por muito tempo (ou na virada de patch), as estatísticas não eram renovadas; agora renovam a cada hora e a cada nova seleção, e os dados do patch anterior são descartados.
- Registro de erros em arquivo (draftbot.log) e diagnóstico mostram a pasta de dados.
- Testes automáticos do programa e da página.

## v2.1.1
- A coluna Recomendações passou a ser igual para qualquer conta; a experiência pessoal conta só no Seu pool.

## v2.1.0
- Chance estimada de vitória, rotas inimigas fixáveis, envio automático ao travar, Seu pool detalhado, janela compacta, diagnóstico, correções de cache e segurança.
