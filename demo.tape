# vhs demo.tape  ->  demo.gif
# Needs Docker and jq. Starts the API and the fixture site, then scrapes the article.

Output demo.gif

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 720
Set TypingSpeed 40ms

Hide
Type "docker compose up --build -d > /dev/null 2>&1 && sleep 3 && clear"
Enter
Sleep 60s
Show

Type `curl -s -X POST localhost:8080/scrape-url -H 'content-type: application/json' -d '{"url":"http://fixture.test/article.html"}' | jq '{success, rung, ladder: [.ladder[] | {name, status, reason}]}'`
Sleep 500ms
Enter
Sleep 8s

Hide
Type "docker compose down > /dev/null 2>&1"
Enter
Sleep 5s
