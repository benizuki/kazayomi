# Ayame。公式のバイナリ配布がないため、タグを指定してソースからビルドする。
FROM golang:1.27 AS build
ARG AYAME_VERSION=2026.2.1
RUN git clone --depth 1 --branch ${AYAME_VERSION} https://github.com/OpenAyame/ayame.git /src
WORKDIR /src
RUN CGO_ENABLED=0 go build -o /ayame ./cmd/ayame

FROM gcr.io/distroless/static-debian12
COPY --from=build /ayame /ayame
COPY config.ini /config.ini
EXPOSE 3000
ENTRYPOINT ["/ayame", "-C", "/config.ini"]
