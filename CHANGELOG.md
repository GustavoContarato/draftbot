# Mudanças

## v2.8.0
- Dados Mestre+ próprios pela API oficial da Riot (opcional, com a sua chave gratuita): o DraftBot junta partidas ranqueadas de jogadores Mestre+ do patch e mostra a taxa de vitória de cada runa, uma página de runas "Mestre+ do patch", as builds de itens em ordem, feitiços, e o recorte da situação: contra o seu oponente de rota e itens que ganham mais contra time de dano mágico ou físico. Com dados suficientes (200+ partidas do campeão), a página recomendada passa a ser a melhor desses dados.
- A coleta continua de onde parou a cada vez que o DraftBot abre. Também pode rodar todo dia no GitHub (com a chave pessoal da Riot), e o DraftBot de todo mundo baixa e soma esses dados, sem precisar de chave.
- Procura versão nova a cada 15 minutos e sempre que a janela é aberta.

## v2.7.1
- Ícones de campeões agora vêm do Data Dragon (o repositório oficial e atual da Riot): alguns retratos guardados no cliente eram de artes antigas (ex.: Ezreal). Sem internet, usa os do cliente.

## v2.7.0
- Ícones do jogo (pequenos): campeões nas recomendações, no pool, na seleção e nos bans; runas, feitiços e itens na build. Vêm do próprio cliente do LoL; com ele fechado, da CommunityDragon. Ficam guardados no PC.
- Mais opções de runas: além da página recomendada (a do confronto ou a mais usada), aparecem a outra página da OP.GG e as páginas que o próprio cliente do LoL sugere para o campeão e a rota. A recomendada vem primeiro e marcada; clique em outra para ver e enviar.

## v2.6.2
- "Seu pool" agora mostra exatamente a mesma chance da coluna Recomendações, só que filtrada para os campeões que você joga (com seus jogos, KDA e maestria ao lado, sem mexer na porcentagem).

## v2.6.1
- Corrigido: no "Seu pool", 1 ou 2 vitórias com um campeão davam um bônus grande demais (ex.: Nautilus com 1 jogo passava o 1º recomendado). Agora o seu resultado só pesa de verdade com dezenas de partidas.
- No "Seu pool", a chance mostra "para você" e, embaixo, a chance geral (a mesma da coluna do meio), para comparar.

## v2.6.0
- As versões novas agora vêm direto das releases do GitHub (com a impressão digital do .zip que o próprio GitHub calcula). Não é mais preciso Google Drive nem editar o aviso à mão: publicou a release, todo mundo recebe o "Atualizar agora".

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
