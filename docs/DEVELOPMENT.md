# Origem e limites desta versão

Esta é uma evolução de desenvolvimento do código Python recuperado do commit
[`4e46b9f`](https://github.com/n456k7z4wy-hash/Carriola-Downloader/commit/4e46b9f)
(`carriola_v6.2.py`), posteriormente removido no commit `23f9d18`.
Na revisão analisada (`d7c281c`), a branch principal continha somente `README.md`
e `update.xml`. As releases 6.1, 6.2, 14, 15, 15.1 e 15.2 continham executáveis,
sem código-fonte adicional anexado.

O README histórico, o Python recuperado e as notas das releases foram usados
para manter downloads de vídeo/áudio, playlists, miniaturas, notificações,
modo compacto, seleção de pasta e busca. A versão `16.0.0.dev1` identifica
esta base recuperada e não afirma equivalência com o executável 15.2.
O `update.xml` continua apontando para o instalador publicado 15.2.

## Mudanças verificáveis

- `engine.py`: seleção de vídeo com áudio, limite por dois eixos, formato final
  real após FFmpeg, MP4/MKV, MP3/M4A/WAV e tratamento separado de capas no WAV.
- `queue_manager.py`: fila sequencial com cancelamento independente, repetição,
  resultados parciais de playlists e comunicação por mensagens.
- `storage.py`: histórico/configurações SQLite no diretório do usuário;
  recuperação de tarefas interrompidas; importação da pasta da configuração antiga.
- `ui.py`: interface escura, fila e histórico integrados, busca, detalhes,
  configuração de FFmpeg, notificações opcionais e nenhum acesso a widgets pelo worker.
- `services.py`: cache de miniaturas com hash completo, limite de espaço e idade;
  consulta de releases sem substituir o Python, apagar o programa ou executar instaladores.

## Comportamento

O encerramento aguarda a etapa atual de rede/FFmpeg para evitar destruir um
arquivo durante a conversão. Itens concluídos permanecem salvos; arquivos `.part`
podem ser retomados ao tentar novamente quando a plataforma permitir.

O limite de qualidade considera o menor e o maior eixo (incluindo DCI 4K),
sem impor H.264. Assim, a melhor fonte pode usar VP9/AV1; MP4 descreve o contêiner,
não uma promessa de compatibilidade universal de codecs. Não há transcodificação
de vídeo. Uma fonte sem áudio produz uma mensagem de erro, em vez de sucesso
com um arquivo mudo. A resolução real disponível pode ser inferior ao limite escolhido.

Playlists do YouTube são explícitas na interface. Conteúdo que depende de login
pode falhar: esta base não inclui um fluxo de cookies/autenticação.
Animações e efeitos específicos citados nas releases 15.x não foram recuperados.

## Testar

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
```

Os testes de mídia usam um servidor HTTP local com fontes geradas pelo FFmpeg;
não baixam vídeos de terceiros. Exercitam a criação de arquivo 4K com áudio,
MP4/MKV, MP3/M4A/WAV, nomes Unicode, pasta com `%` e repetição sem sobrescrever
a saída já concluída. Os testes de interface precisam de uma sessão gráfica;
em Linux, use `xvfb-run -a python -m pytest -q tests/test_ui.py`.

O workflow testa Python 3.11 no Linux e 3.13 no Windows. A integração de mídia
é pulada automaticamente quando FFmpeg/FFprobe não estão disponíveis.

## Validação desta entrega

- 45 testes passaram em Python 3.12/Linux, incluindo a interface Tk em tela virtual.
- Arquivos 4K com vídeo e áudio confirmados pelo FFprobe, em MP4 e MKV.
- MP3/M4A com capa incorporada e WAV sem tentativa de incorporar capa.
- Fila, cancelamento individual, repetição, recuperação do histórico, busca e preferências.
- Instalação do pacote em ambiente virtual, compilação Python e análise Ruff passaram.
- Janela inspecionada em 1100×830 e 900×650; botões permaneceram dentro da largura disponível.

A validação local usou mídia sintética servida por HTTP local. Downloads reais
no YouTube/Instagram/X e o executável empacotado no Windows ainda precisam
ser testados nesse ambiente. Nenhum novo instalador foi produzido nesta entrega.

## Gerar executável no Windows

Com FFmpeg, FFprobe e Deno instalados, abra o PowerShell na pasta do projeto:

```powershell
.\scripts\build_windows.ps1 -FFmpegDirectory 'C:\ffmpeg\bin' -DenoPath 'C:\caminho\deno.exe'
```

O resultado é uma pasta `dist\CarriolaDownloaderDev`, com executável e
dependências. Este fluxo não cria nem publica um instalador Setup.exe,
não modifica a release existente e não altera o feed de atualizações.

## Referências técnicas

- [API e exemplos de incorporação do yt-dlp](https://github.com/yt-dlp/yt-dlp#embedding-yt-dlp)
- [Dependências de JavaScript do yt-dlp](https://github.com/yt-dlp/yt-dlp/wiki/EJS)
- [Documentação do CustomTkinter](https://customtkinter.tomschimansky.com/documentation/)
