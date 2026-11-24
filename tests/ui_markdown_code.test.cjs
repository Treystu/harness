const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

function loadRenderer() {
  const elements = new Map();
  const makeElement = () => ({
    hidden: false, disabled: false, title: "", value: "", style: {},
    addEventListener() {}, appendChild() {}, focus() {},
  });
  const document = {
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, makeElement());
      return elements.get(selector);
    },
    querySelectorAll() { return []; },
    getElementById(id) { return this.querySelector(`#${id}`); },
    createElement() { return makeElement(); },
  };
  const window = { addEventListener() {} };
  const context = vm.createContext({
    window, document,
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    console,
    setInterval() { return 1; },
    clearInterval() {},
    setTimeout() { return 1; },
    clearTimeout() {},
  });
  const appPath = path.join(__dirname, "..", "harness", "ui", "app.js");
  vm.runInContext(
    fs.readFileSync(appPath, "utf8") + "\nwindow.__test = { render: renderSimpleMarkdown };",
    context);
  return window.__test.render;
}

// The text a browser would give back for a `<pre><code>` segment: the HTML
// entity the renderer escaped, decoded.
function codeText(html) {
  const match = html.match(/<pre><code>([\s\S]*?)<\/code><\/pre>/);
  assert.ok(match, `no code block rendered in: ${html}`);
  return match[1]
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");
}

const render = loadRenderer();

test("the exponent operator survives a fenced code block", () => {
  const source = [
    "import math",
    "",
    "def scale(values):",
    "    return [10 ** e[1] for e in values]",
    "",
    "def grow(k):",
    "    return 10 ** k",
  ].join("\n");
  const html = render("```python\n" + source + "\n```");
  assert.equal(codeText(html), source);
  assert.ok(!html.includes("<strong>"), "no bold inside the code block");
});

test("other inline markers inside code stay literal", () => {
  const source = "flag = a ** b  # _not italic_ and `not inline code`";
  const html = render("```text\n" + source + "\n```");
  assert.equal(codeText(html), source);
});

test("inline code is not formatted either", () => {
  const html = render("Use `10 ** exp` in the script.");
  assert.ok(html.includes("<code>10 ** exp</code>"), html);
  assert.ok(!html.includes("<strong>"), html);
});

test("bold outside code still renders and code keeps its place", () => {
  const source = "total = 10 ** 3";
  const html = render(
    "**Note** the scale:\n\n```python\n" + source + "\n```\n\nDone **now**.");
  assert.ok(html.includes("<strong>Note</strong>"), html);
  assert.ok(html.includes("<strong>now</strong>"), html);
  assert.equal(codeText(html), source);
  // The code block is a block of its own, not wrapped in a paragraph.
  assert.ok(!html.includes("<p><pre>"), html);
});

test("two blocks do not swallow each other", () => {
  const first = "a = 2 ** 3";
  const second = "b = 4 ** 5";
  const html = render(
    "```python\n" + first + "\n```\n\ntext\n\n```python\n" + second + "\n```");
  const found = [...html.matchAll(/<pre><code>([\s\S]*?)<\/code><\/pre>/g)]
    .map((m) => m[1]);
  assert.deepEqual(found.map((s) => s.replace(/&amp;/g, "&")), [first, second]);
});
