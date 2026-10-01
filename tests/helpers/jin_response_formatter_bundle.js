const fs = require("fs");
const path = require("path");

const root = process.cwd();
eval(fs.readFileSync(path.join(root, "ui", "static", "js", "jin-ui-utils.js"), "utf8"));
eval(fs.readFileSync(path.join(root, "ui", "static", "js", "chat-response-formatter.js"), "utf8"));
