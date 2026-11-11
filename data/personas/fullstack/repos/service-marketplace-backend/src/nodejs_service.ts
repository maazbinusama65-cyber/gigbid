import http from 'node:http';

const server = http.createServer((req, res) => {
  res.setHeader('content-type', 'application/json');
  res.end(JSON.stringify({ ok: true, path: req.url }));
});
server.listen(3000);
