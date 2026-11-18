# Mudanças

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
