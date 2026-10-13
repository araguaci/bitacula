const login = document.querySelector("#login");
const app = document.querySelector("#app");
const view = document.querySelector("#view");
const title = document.querySelector("#title");
const subtitle = document.querySelector("#subtitle");
const loginError = document.querySelector("#login-error");
let csrf = "";
let current = "overview";
let timer = 0;

const titles = {
  overview: ["Visão geral", "Capacidade do servidor e o IP do laboratório"],
  databases: ["Bancos", "PostgreSQL, MySQL e Redis. As senhas dos bancos não são exibidas."],
  containers: ["Containers", "O que está em execução nesta VPS"],
  access: ["Acesso", "Laboratório nas portas 3306, 6379 e 5432, com usuário e senha do painel"],
  backups: ["Backups", "Cópias do PostgreSQL e do MySQL feitas neste servidor"],
};

function text(value) {
  return document.createTextNode(value == null ? "" : String(value));
}

function el(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content != null) node.append(text(content));
  return node;
}

function bytes(value) {
  const n = Number(value) || 0;
  if (n >= 1024 ** 3) return (n / 1024 ** 3).toFixed(1) + " GB";
  if (n >= 1024 ** 2) return (n / 1024 ** 2).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(0) + " KB";
  return n + " B";
}

function uptime(seconds) {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return [d ? d + " d" : "", h ? h + " h" : "", m + " min"].filter(Boolean).join(" ");
}

function barClass(percent) {
  if (percent >= 90) return "bar hot";
  if (percent >= 75) return "bar warn";
  return "bar";
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  if (csrf && options.method === "POST") headers["X-CSRF"] = csrf;
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && path !== "/api/login") {
    showLogin();
    throw new Error(data.error || "Sessão encerrada.");
  }
  if (!response.ok) throw new Error(data.error || data.message || "Falha na consulta.");
  return data;
}

function showLogin() {
  app.hidden = true;
  login.hidden = false;
  clearInterval(timer);
}

function showApp() {
  login.hidden = true;
  app.hidden = false;
}

document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.hidden = true;
  const form = new FormData(event.target);
  try {
    const data = await api("/api/login", {
      method: "POST",
      body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
    });
    csrf = data.csrf;
    document.querySelector("#who").textContent = data.user;
    showApp();
    openView(current);
  } catch (error) {
    loginError.hidden = false;
    loginError.textContent = error.message;
  }
});

document.querySelector("#logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST", body: "{}" }).catch(() => {});
  csrf = "";
  showLogin();
});

document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => openView(button.dataset.view));
});

function openView(name) {
  current = name;
  document.querySelectorAll("nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
  });
  title.textContent = titles[name][0];
  subtitle.textContent = titles[name][1];
  clearInterval(timer);
  load();
  if (name === "overview") timer = setInterval(load, 15000);
  if (name === "backups") timer = setInterval(load, 4000);
}

async function load() {
  view.replaceChildren(el("p", "muted", "Carregando…"));
  try {
    if (current === "overview") renderOverview(await api("/api/overview"));
    if (current === "databases") renderDatabases(await api("/api/databases"));
    if (current === "containers") renderContainers(await api("/api/containers"));
    if (current === "access") renderAccess(await api("/api/access"));
    if (current === "backups") renderBackups(await api("/api/backups"));
  } catch (error) {
    view.replaceChildren(el("p", "error", error.message));
  }
}

function metric(label, value, percent) {
  const card = el("article", "card metric");
  card.append(el("span", "", label), el("strong", "", value));
  if (percent != null) {
    const bar = el("div", barClass(percent));
    const fill = document.createElement("i");
    fill.style.width = Math.max(0, Math.min(100, percent)) + "%";
    bar.append(fill);
    card.append(bar);
  }
  return card;
}

function renderOverview(data) {
  const mem = Math.round(100 * data.memory.used / data.memory.total);
  const wrap = el("div", "metrics");
  wrap.append(
    metric("CPU", data.cpu_percent + "%", data.cpu_percent),
    metric("Memória", bytes(data.memory.used) + " / " + bytes(data.memory.total), mem),
    metric("Disco", data.disk.percent + "%", data.disk.percent),
    metric("No ar", uptime(data.uptime_seconds)),
  );
  const info = el("article", "card");
  info.append(el("h3", "", data.hostname));
  const list = document.createElement("p");
  list.className = "note";
  list.append(
    text("IP público "),
    el("span", "mono", data.public_ip),
    text(" · carga " + data.load.join(" / ")),
    text(" · " + data.containers_running + " containers em execução de " + data.containers_total),
  );
  info.append(list);
  const access = el("article", "card");
  access.append(el("h3", "", "Laboratório"));
  access.append(el("p", "", "O IP abaixo entra no Postgres, MySQL e Redis publicados, com a senha de cada banco."));
  access.append(el("p", "mono", data.lab_ip || "não registrado"));
  access.append(el("p", "note", "Painel: " + data.panel_url));
  const grid = el("div", "grid-2");
  grid.append(info, access);
  view.replaceChildren(wrap, grid);
}

function dbTable(items) {
  const table = document.createElement("table");
  const head = document.createElement("tr");
  ["Banco", "Tamanho"].forEach((name) => head.append(el("th", "", name)));
  table.append(head);
  items.forEach((item) => {
    const row = document.createElement("tr");
    row.append(el("td", "mono", item.name), el("td", "", bytes(item.bytes)));
    table.append(row);
  });
  if (!items.length) {
    const row = document.createElement("tr");
    row.append(el("td", "", "Nenhum banco de aplicação"));
    table.append(row);
  }
  return table;
}

function instanceCard(engine, item) {
  const card = el("article", "card");
  const head = el("h3", "", engine + " · " + item.container);
  card.append(head);
  const where = item.port ? item.host + ":" + item.port : item.host;
  const line = el("p", "note");
  line.append(text(where));
  if (item.user) line.append(text(" · usuário " + item.user));
  card.append(line);
  const pill = el("span", item.open_to_lab ? "pill" : "pill off", item.open_to_lab ? "aberto ao laboratório" : "só interno");
  card.append(pill);
  if (item.error) card.append(el("p", "error", item.error));
  if (item.databases) card.append(dbTable(item.databases));
  if (item.memory != null) {
    card.append(el("p", "", (item.ok ? "Respondendo" : "Sem resposta") + (item.memory ? " · memória " + item.memory : "") + (item.clients ? " · " + item.clients + " clientes" : "")));
  }
  return card;
}

function renderDatabases(data) {
  const stack = el("div", "stack");
  const host = data.public_ip || "o IP público deste servidor";
  stack.append(el("p", "note", "Conexão a partir do laboratório: host " + host + ", com o usuário abaixo e a senha guardada na aplicação. Este painel não mostra senha de banco."));
  data.postgres.forEach((item) => stack.append(instanceCard("PostgreSQL", item)));
  data.mysql.forEach((item) => stack.append(instanceCard("MySQL", item)));
  data.redis.forEach((item) => stack.append(instanceCard("Redis", item)));
  view.replaceChildren(stack);
}

function renderContainers(data) {
  const card = el("article", "card");
  const table = document.createElement("table");
  const head = document.createElement("tr");
  ["Nome", "Imagem", "Estado", "Portas"].forEach((name) => head.append(el("th", "", name)));
  table.append(head);
  data.items.forEach((item) => {
    const row = document.createElement("tr");
    row.append(
      el("td", "mono", item.name),
      el("td", "", item.image),
      el("td", "", item.status),
      el("td", "mono", item.ports || "—"),
    );
    table.append(row);
  });
  card.append(table);
  view.replaceChildren(card);
}

function renderAccess(data) {
  const status = el("article", "card");
  status.append(el("h3", "", "IP do laboratório"));
  status.append(el("p", "mono", data.lab_ip || "não registrado"));
  status.append(el("p", "note", "Estações que continuam liberadas: " + data.stations.filter((ip) => ip !== data.lab_ip).join(", ")));
  const table = document.createElement("table");
  const head = document.createElement("tr");
  ["Porta", "IP", "Comentário"].forEach((name) => head.append(el("th", "", name)));
  table.append(head);
  data.rules.forEach((rule) => {
    const row = document.createElement("tr");
    row.append(el("td", "mono", rule.port), el("td", "mono", rule.ip), el("td", "", rule.comment));
    table.append(row);
  });
  status.append(table);

  const formCard = el("article", "card");
  formCard.append(el("h3", "", "Trocar o IP público do laboratório"));
  formCard.append(el("p", "note", "Use o IP público que o servidor enxerga. No laboratório: curl -4 ifconfig.me. O endereço da rede local não chega até esta VPS."));
  const form = document.createElement("form");
  form.className = "form-row";
  const label = el("label", "", "Novo IP");
  const input = document.createElement("input");
  input.name = "ip";
  input.required = true;
  input.placeholder = "0.0.0.0";
  input.pattern = "^(?:\\d{1,3}\\.){3}\\d{1,3}$";
  label.append(input);
  const button = el("button", "primary", "Liberar este IP");
  button.type = "submit";
  const message = el("p", "note", "");
  form.append(label, button);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!confirm("Liberar " + input.value + " e retirar o IP antigo do laboratório?")) return;
    button.disabled = true;
    try {
      const result = await api("/api/access/lab-ip", { method: "POST", body: JSON.stringify({ ip: input.value.trim() }) });
      message.className = "ok";
      message.textContent = result.message;
      renderAccess(await api("/api/access"));
    } catch (error) {
      message.className = "error";
      message.textContent = error.message;
      button.disabled = false;
    }
  });
  formCard.append(form, message);

  const pass = el("article", "card");
  pass.append(el("h3", "", "Senha deste painel"));
  const passForm = document.createElement("form");
  passForm.className = "stack";
  const current = document.createElement("input");
  current.type = "password";
  current.placeholder = "Senha atual";
  current.required = true;
  const next = document.createElement("input");
  next.type = "password";
  next.placeholder = "Nova senha (mínimo 12)";
  next.required = true;
  next.minLength = 12;
  const passButton = el("button", "primary", "Alterar senha");
  passButton.type = "submit";
  const passMsg = el("p", "note", "");
  passForm.append(current, next, passButton, passMsg);
  passForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await api("/api/password", {
        method: "POST",
        body: JSON.stringify({ current: current.value, new: next.value }),
      });
      passMsg.className = "ok";
      passMsg.textContent = result.message;
      current.value = "";
      next.value = "";
    } catch (error) {
      passMsg.className = "error";
      passMsg.textContent = error.message;
    }
  });
  pass.append(passForm);

  const grid = el("div", "stack");
  grid.append(status, formCard, pass);
  view.replaceChildren(grid);
}

function renderBackups(data) {
  const card = el("article", "card");
  const actions = el("div", "actions");
  const choices = [
    [["postgres"], "PostgreSQL", "Gerar uma cópia de todos os Postgres agora?"],
    [["mysql"], "MySQL", "Gerar uma cópia de todos os MySQL agora?"],
    [["postgres", "mysql"], "PostgreSQL e MySQL", "Gerar uma cópia do Postgres e do MySQL agora?"],
  ];
  choices.forEach(([engines, label, question], index) => {
    const button = el("button", index === 2 ? "primary" : "ghost", data.running ? "Backup em andamento…" : label);
    button.disabled = data.running;
    button.addEventListener("click", async () => {
      if (!confirm(question)) return;
      actions.querySelectorAll("button").forEach((item) => {
        item.disabled = true;
      });
      try {
        await api("/api/backups/run", { method: "POST", body: JSON.stringify({ engines }) });
        load();
      } catch (error) {
        view.prepend(el("p", "error", error.message));
        actions.querySelectorAll("button").forEach((item) => {
          item.disabled = false;
          item.textContent = choices.find((choice) => choice[0].join() === item.dataset.engines)[1];
        });
      }
    });
    button.dataset.engines = engines.join();
    actions.append(button);
  });
  card.append(actions);
  if (data.log) card.append(el("pre", "", data.log));
  const table = document.createElement("table");
  const head = document.createElement("tr");
  ["Quando", "Motores", "Pasta", "Tamanho", "Estado"].forEach((name) => head.append(el("th", "", name)));
  table.append(head);
  data.items.forEach((item) => {
    const row = document.createElement("tr");
    row.append(
      el("td", "", item.when),
      el("td", "", item.engines || "PostgreSQL"),
      el("td", "mono", item.stamp),
      el("td", "", bytes(item.bytes)),
      el("td", "", item.ok ? "ok" : "com falha"),
    );
    table.append(row);
  });
  card.append(table);
  view.replaceChildren(card);
}

function tick() {
  document.querySelector("#clock").textContent = new Date().toLocaleString("pt-BR");
}
setInterval(tick, 1000);
tick();

api("/api/session").then((data) => {
  csrf = data.csrf;
  document.querySelector("#who").textContent = data.user;
  showApp();
  openView("overview");
}).catch(() => showLogin());
