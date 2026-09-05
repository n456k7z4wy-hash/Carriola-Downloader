# Carriola Vídeos Downloader

Aplicativo desktop para baixar vídeos e áudios do YouTube, Instagram e X,
com interface escura e organização dos downloads.

**Versão publicada:** [15.2 — baixar o instalador para Windows](https://github.com/n456k7z4wy-hash/Carriola-Downloader/releases/tag/v15.2).

**Código desta branch:** `16.0.0.dev1`, uma versão de desenvolvimento baseada
no Python 6.2 recuperado do histórico. O código-fonte da versão 15.2 não está
disponível neste repositório. Veja a [origem e os limites desta versão](docs/DEVELOPMENT.md).

## O que esta versão de desenvolvimento oferece

- Fila de downloads: adicione vários links, cancele cada item e tente novamente.
- Vídeos em MP4 ou MKV, com áudio, na melhor resolução disponível ou com limite
  de 4K, 1440p, 1080p, 720p ou 480p. Vídeos verticais e ultrawide são considerados.
- Extração de áudio MP3 (320 kbps), M4A ou WAV, com metadados. MP3/M4A podem incluir
  capa quando ela estiver disponível; WAV não inclui capa.
- Playlists do YouTube, progresso por item e indicação de resultados parciais.
- Histórico persistente com busca, miniaturas e acesso aos arquivos e pastas.
- Retomada de arquivos parciais quando suportada, identificação de arquivos por ID
  e qualidade, e nomes com acentos/emojis tratados para o Windows.
- Preferências persistentes, modo compacto, logs rotativos e notificações do Windows.

## Executar a versão de desenvolvimento

1. Instale [Python 3.11 ou superior](https://www.python.org/downloads/windows/).
2. Instale [FFmpeg e FFprobe](https://ffmpeg.org/download.html) na mesma pasta,
   por exemplo `C:\ffmpeg\bin`, e adicione-a ao PATH ou selecione o FFmpeg em Preferências.
3. Para o YouTube, instale também o [Deno](https://docs.deno.com/runtime/getting_started/installation/)
   e deixe `deno.exe` no PATH.
4. Baixe ou clone **esta branch**, extraia a pasta e execute `instalar.bat`.
5. Nas próximas vezes, use `iniciar.bat`.

Alternativa pelo terminal, na pasta do projeto:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe -m carriola_downloader
```

Cole um link, escolha Vídeo ou Áudio, formato, qualidade e pasta e clique em
**Adicionar à fila**. Se o link contiver uma playlist, marque **Playlist completa**
para baixar todos os itens. Um link que aponta somente para uma playlist seleciona
essa opção automaticamente.

## Histórico e atualização

Os dados desta versão ficam em `%LOCALAPPDATA%\CarriolaDownloaderDev` no Windows.
Ao limpar o histórico, os vídeos e áudios salvos permanecem no computador.
Downloads interrompidos reaparecem na próxima abertura para repetição manual.

Em Preferências, **Consultar versão publicada** abre, mediante escolha do usuário,
a página da release. O aplicativo não substitui executáveis automaticamente.
Para atualizar o motor desta versão em código-fonte, feche o aplicativo e execute:

```powershell
.venv\Scripts\python.exe -m pip install -U "yt-dlp[default]"
```

Conteúdo privado/restrito pode exigir autenticação não implementada nesta base.
O formato MP4 pode usar codecs modernos como AV1/VP9 conforme a fonte; a qualidade
selecionada é um limite, não uma conversão para uma resolução maior.

## Desenvolvimento

Consulte [testes, arquitetura e empacotamento Windows](docs/DEVELOPMENT.md).
Esta branch não publica um novo instalador nem modifica o `update.xml` da versão 15.2.
