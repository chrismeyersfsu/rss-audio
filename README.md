# rss-audio
Convert website to podcast

```
curl -X POST \
  http://your-service-url/convert \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://paddlingmag.com/stories/features/legendary-43-year-family-canoe-story/",
    "title": "Legendary 43-Year Family Canoe Story"
  }'
```


```
docker build -t ghcr.io/chrismeyersfsu/rss-audio:latest .
docker push ghcr.io/chrismeyersfsu/rss-audio:latest
```
