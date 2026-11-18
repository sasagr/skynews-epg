# skynews-epg

An XMLTV guide for the UK news channel **Sky News**, rebuilt every four hours by a GitHub Action.

The source is **Sky UK's own guide API** — the one behind sky.com's TV guide — which answers without
a key, from yesterday to a week ahead, with a title, a synopsis and a picture for every programme.
It is the UK counterpart of [skytg24-epg](https://github.com/sasagr/skytg24-epg), which reads Sky
Italia's guide.

## Use it

| | |
|---|---|
| **EPG URL** | `https://raw.githubusercontent.com/sasagr/skynews-epg/main/skynews.xml` |
| **tvg-id** | `SkyNews.uk` |
| **Logo** | `https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/united-kingdom/sky-news-uk.png` |

The tvg-id must match exactly: XMLTV consumers tie a programme to a channel by the `channel=`
attribute, so a mismatch shows the channel with an empty guide rather than an error.

## Times are British

Sky's API answers in epoch seconds; every time is written in Europe/London (+0000 in winter,
+0100 in summer), and a player converts to wherever it is.

## Why it merges

Sky stops answering for a day once it is two days old, so the hours already aired survive only in
the file committed by earlier runs. Each run keeps the committed guide before the first programme
Sky returns and takes Sky's answer from there on. Three days of history are kept.

## Run it yourself

```bash
python3 generate.py
```

Standard library only.
