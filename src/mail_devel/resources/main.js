function element(tag, attrs) {
  const ele = document.createElement(tag);
  if (!attrs)
    return ele;

  for (let key in attrs)
    ele.setAttribute(key, attrs[key]);
  return ele;
}

function vis(selector, visible) {
  const elements = document.querySelectorAll(selector);
  if (!elements)
    return

  for (const element of elements)
    if (visible)
      element.classList.remove("hidden");
    else
      element.classList.add("hidden");
}

class MailClient {
  constructor() {
    this.mailboxes = document.getElementById("mailboxes");
    this.mailbox = document.querySelector("#mailbox table tbody");
    this.fixed_headers = ["from", "to", "cc", "bcc", "subject"];
    this.mailbox_name = null;
    this.mail_uid = null;
    this.mail_selected = null;
    this.content_mode = "html";
    this.editor_mode = "simple";
  }

  async visibility() {
    vis("#btn-html", this.content_mode !== "html");
    vis("#btn-plain", this.content_mode !== "plain");
    vis("#btn-source", this.content_mode !== "source");
    vis("#content iframe#html", this.content_mode === "html");
    vis("#content textarea#plain", this.content_mode === "plain");
    vis("#content textarea#source", this.content_mode === "source");
    vis("#editor .header .extra", this.editor_mode === "advanced");

    document.getElementById("btn-advanced").innerText = (
      `${this.editor_mode === "simple" ? "Advanced" : "Simple"} View`
    );
  }

  async idle() {
    const self = this;

    await this.fetch_mailboxes();
    if (this.mailbox_name)
      await this.fetch_mailbox(this.mailbox_name);

    setTimeout(() => {self.idle();}, 2000);
  }

  async set_flag(flag, method) {
    if (this.mailbox_name && this.mail_uid) {
      await fetch(
        `/api/${this.mailbox_name}/${this.mail_uid}/flags/seen`,
        {method: method},
      );
    }
  }

  async fetch_data(...path) {
    try {
      const response = await fetch(path.length ? `/api/${path.join('/')}` : "/api");
      if (response.status !== 200)
        return null;

      return await response.json();
    } catch (TypeError) {
      return null;
    }
  }

  async post_data(data, ...path) {
    try {
      const response = await fetch(
        path.length ? `/api/${path.join('/')}` : "/api",
        {
          method: "POST",
          headers: {
            "Accept": "application/json",
            "Content-Type": "application/json",
          },
          body: JSON.stringify(data),
        },
      );
      if (response.status !== 200)
        return null;

      return await response.json();
    } catch (TypeError) {
      return null;
    }
  }

  async _mail_row(row, msg) {
    const self = this;

    if ((msg?.flags || []).indexOf("seen") < 0)
      row.classList.add("unseen");
    else
      row.classList.remove("unseen");

    function cell (idx, val) {
      let ele;
      if (idx < row.children.length)
        ele = row.children[idx];
      else {
        ele = document.createElement("td");
        row.append(ele);
      }

      ele.innerHTML = (val || "").replace("<", "&lt;");
    }

    cell(0, msg.header?.from);
    cell(1, msg.header?.to);
    cell(2, msg.header?.subject);
    cell(3, (new Date(msg.date)).toLocaleString());

    row.addEventListener("click", (ev) => {
      let element = ev.target;
      while (element && !element.uid) {
        element = element.parentElement;
      }

      if (element.uid) {
        if (self.mail_selected)
          self.mail_selected.classList.remove("selected");

        self.mail_selected = element;
        self.mail_selected.classList.add("selected");
        self.fetch_mail(element.uid);
      }
    });
  }

  async fetch_mailboxes() {
    const self = this;
    const data = await this.fetch_data();
    if (data === null)
      return;

    for (const opt of this.mailboxes.options) {
      const idx = data.indexOf(opt.value);
      if (idx >= 0)
        data.splice(idx, 1);
      else
        opt.remove()
    }

    for (const mailbox of data) {
      this.mailboxes.add(new Option(mailbox, mailbox));
    }

    if (this.mailboxes.selectedIndex < 0) {
      this.mailboxes.selectedIndex = 0;
      if (this.mailboxes.options[0]) {
        await self.fetch_mailbox(this.mailboxes.options[0].value);
      }
    }
  }

  async fetch_mailbox(mailbox_name) {
    const self = this;
    const data = await this.fetch_data(mailbox_name);
    if (data === null)
      return;

    if (this.mailbox_name !== mailbox_name) {
      this.mail_uid = null;
      this.mailbox.innerHTML = "";
    }

    this.mailbox_name = mailbox_name;
    const missing_msg = [];
    const uids = [];
    for (const msg of data) {
      uids.push(msg.uid);

      let found = false;
      for (const line of this.mailbox.children) {
        if (line.uid === msg.uid) {
          found = true;
          await self._mail_row(line, msg);
          break;
        }
      }

      if (!found)
        missing_msg.push(msg);
    }

    for (const msg of missing_msg) {
      const row = element("tr");
      this.mailbox.append(row);
      row.uid = msg.uid;
      await self._mail_row(row, msg);
    }

    for (const line of this.mailbox.children) {
      if (uids.indexOf(line.uid) < 0)
        line.remove();
    }
  }

  async fetch_mail(uid) {
    const self = this;
    const data = await this.fetch_data(this.mailbox_name, uid);
    if (data === null)
      return;

    self.mail_uid = uid;

    document.querySelector("#header-from input").value = data?.header?.from || "";
    document.querySelector("#header-to input").value = data?.header?.to || "";
    document.querySelector("#header-cc input").value = data?.header?.cc || "";
    document.querySelector("#header-bcc input").value = data?.header?.bcc || "";
    document.querySelector("#header-subject input").value = data?.header?.subject || "";
    document.querySelector("#content textarea#source").value = data?.content || "";
    document.querySelector("#content textarea#plain").value = data?.body_plain || "";
    document.querySelector("#content iframe#html").srcdoc = data?.body_html || "";

    const dropdown = document.querySelector("#btn-dropdown div");
    dropdown.innerHTML = "";

    for (const attachment of data?.attachments || []) {
      const link = document.createElement("a");
      link.href = `/api/${this.mailbox_name}/${uid}/attachment/${attachment}`;
      link.innerHTML = attachment;
      dropdown.append(link);
    }

    if (!data?.body_html && self.content_mode === "html")
      self.content_mode = "plain";

    await self.visibility();
  }

  async add_header(key = null, value = null) {
    const table = document.getElementById("editor-header");
    const row = element("tr", {"class": "extra"});
    const key_td = element("th"), value_td = element("td"), btn_td = element("td");
    const btn = element("button", {"type": "button", "class": "delete"});
    const key_input = element("input", {"type": "input"});
    const value_input = element("input", {"type": "input"});

    btn.innerHTML = "&#10006;";
    if (key) key_input.value = key;
    if (value) value_input.value = value;

    key_td.append(key_input);
    value_td.append(value_input);
    btn_td.append(btn);

    btn.addEventListener("click", (ev) => {row.remove();});

    row.append(key_td);
    row.append(value_td);
    row.append(btn_td);
    table.append(row);

    await this.visibility();
  }

  async send_mail() {
    const headers = {};
    for (const key of this.fixed_headers)
      headers[key] = document.querySelector(`#editor-${key} input`).value;

    for (const row of document.querySelectorAll("#editor .header .extra")) {
      const inputs = row.querySelectorAll("input");
      if (inputs.length < 2)
        continue;

      const key = inputs[0].value.trim().toLowerCase();
      const value = inputs[1].value.trim().toLowerCase();
      if (key && value && !this.fixed_headers.includes(key))
        headers[key] = value;
    }

    await this.post_data({
      header: headers,
      body: document.querySelector("#editor-content textarea").value,
    });

    document.querySelector("#editor").classList.add("hidden");
    await this.reset_editor();
  }

  async reply_mail() {
    if (!this.mailbox_name || !this.mail_uid)
      return;

    const data = await this.fetch_data(this.mailbox_name, this.mail_uid, "reply");
    if (data === null)
      return;

    await this.reset_editor(data.header || {});
    document.querySelector("#editor").classList.remove("hidden");
  }

  async reset_editor(header = null, body = null) {
    for (const row of document.querySelectorAll("#editor .header .extra"))
      row.remove();

    if (header)
      for (const key in header) {
        if (!this.fixed_headers.includes(key))
          await this.add_header(key, header[key]);
      }

    for (const key of this.fixed_headers) {
      const element = document.querySelector(`#editor-${key} input`);
      element.value = (header && header[key]) ? header[key] : "";
    }

    document.querySelector("#editor-content textarea").value = body || "";
  }

  async initialize() {
    const self = this;
    this.mailboxes.addEventListener("change", (ev) => {
      self.fetch_mailbox(ev.target.value);
    });
    document.getElementById("btn-html").addEventListener("click", () => {
      self.content_mode = "html";
      self.visibility();
    });
    document.getElementById("btn-plain").addEventListener("click", () => {
      self.content_mode = "plain";
      self.visibility();
    });
    document.getElementById("btn-source").addEventListener("click", () => {
      self.content_mode = "source";
      self.visibility();
    });
    document.getElementById("btn-seen").addEventListener("click", (ev) => {
      self.set_flag("seen", "PUT");
    });
    document.getElementById("btn-unseen").addEventListener("click", (ev) => {
      self.set_flag("seen", "DELETE");
    });
    document.getElementById("btn-new").addEventListener("click", (ev) => {
      document.querySelector("#editor").classList.remove("hidden");
    });
    document.getElementById("btn-cancel").addEventListener("click", (ev) => {
      document.querySelector("#editor").classList.add("hidden");
      self.reset_editor();
    });
    document.getElementById("btn-send").addEventListener("click", (ev) => {
      self.send_mail();
    });
    document.getElementById("btn-reply").addEventListener("click", (ev) => {
      self.reply_mail();
    });
    document.getElementById("btn-advanced").addEventListener("click", (ev) => {
      self.editor_mode = (self.editor_mode === "simple") ? "advanced" : "simple";
      self.visibility();
    });
    document.getElementById("btn-add-header").addEventListener("click", (ev) => {
      self.add_header();
    });

    await this.visibility();
    await this.idle();
  }
}
