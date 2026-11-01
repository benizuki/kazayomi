# Ayame。公式のバイナリ配布がないため、タグを指定してソースからビルドする。
FROM golang:1.27 AS build
ARG AYAME_VERSION=2026.2.1
RUN git clone --depth 1 --branch ${AYAME_VERSION} https://github.com/OpenAyame/ayame.git /src
WORKDIR /src
RUN CGO_ENABLED=0 go build -o /ayame ./cmd/ayame
# バイナリに入るもの（Ayame 本体、依存モジュール、Go の標準ライブラリ）のライセンス文を集める
RUN mkdir -p /licenses/ayame /licenses/go \
 && cp LICENSE /licenses/ayame/ \
 && { cp NOTICE* /licenses/ayame/ 2>/dev/null || true; } \
 && cp "$(go env GOROOT)/LICENSE" /licenses/go/ \
 && CGO_ENABLED=0 go list -deps -f '{{with .Module}}{{if not .Main}}{{.Path}} {{.Dir}}{{end}}{{end}}' ./cmd/ayame | sort -u \
  | while read -r mod dir; do \
      mkdir -p "/licenses/$mod" \
      && find "$dir" -maxdepth 1 -type f \( -iname 'licen[cs]e*' -o -iname 'copying*' -o -iname 'notice*' \) -exec cp {} "/licenses/$mod/" \; ; \
    done

FROM gcr.io/distroless/static-debian12
COPY --from=build /ayame /ayame
COPY --from=build /licenses /licenses
COPY config.ini /config.ini
EXPOSE 3000
ENTRYPOINT ["/ayame", "-C", "/config.ini"]
