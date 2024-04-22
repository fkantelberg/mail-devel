function element(tag, attrs) {
  const ele = document.createElement(tag);
  if (!attrs)
    return ele;

  for (let key in attrs)
    ele.setAttribute(key, attrs[key]);
  return ele;
}

function file_to_base64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.readAsDataURL(file);
    reader.onload = () => resolve(reader.result.replace(/.*,/, ""));
    reader.onerror = reject;
  });
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
    this.users = document.getElementById("accounts");
    this.connection = document.querySelector("#connection input[type=checkbox]");
    this.mailboxes = document.getElementById("mailboxes");
    this.mailbox = document.querySelector("#mailbox table tbody");
    this.fixed_headers = ["from", "to", "cc", "bcc", "subject"];
    this.user_id = null;
    this.mailbox_id = null;
    this.mail_uid = null;
    this.mail_selected = null;
    this.content_mode = "html";
    this.editor_mode = "simple";
    this.config = {};

    const toggle = document.querySelector("#color-scheme input");
    if (document.documentElement.classList.contains("dark"))
      toggle.checked = true;
    else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)
      toggle.checked = true
    else
      toggle.checked = false

    this.reorder(false);
  }

  async swap_theme() {
    const toggle = document.querySelector("#color-scheme input");
    if (toggle.checked) {
      document.documentElement.classList.add("light");
      document.documentElement.classList.remove("dark");
    } else {
      document.documentElement.classList.add("dark");
      document.documentElement.classList.remove("light");
    }

    toggle.checked = !toggle.checked;
  }

  async visibility() {
    vis("#accounts", Boolean(this.config?.multi_user));
    vis("#btn-html", this.content_mode !== "html");
    vis("#btn-plain", this.content_mode !== "plain");
    vis("#btn-source", this.content_mode !== "source");
    vis("#content iframe#html", this.content_mode === "html");
    vis("#content textarea#plain", this.content_mode === "plain");
    vis("#content textarea#source", this.content_mode === "source");
    vis("#editor .header .extra", this.editor_mode === "advanced");
    vis("#editor #btn-add-header", this.editor_mode === "advanced");

    document.getElementById("btn-advanced").innerText = (
      `${this.editor_mode === "simple" ? "Advanced" : "Simple"} View`
    );
  }

  async idle() {
    const self = this;

    if (this.connection.checked) {
        await this.fetch_accounts();

        if (this.user_name)
          await this.fetch_mailboxes(this.user_name);

        if (this.mailbox_id)
          await this.fetch_mailbox(this.mailbox_id);
    }

    setTimeout(() => {self.idle();}, 2000);
  }

  async set_flag(flag, method, uid = null) {
    const mail_uid = uid || this.mail_uid;
    if (this.mailbox_id && mail_uid) {
      await fetch(
        `/api/${this.user_id}/${this.mailbox_id}/${mail_uid}/flags/${flag}`,
        {method: method},
      );
    }
  }

  async fetch_json(path) {
    try {
      const response = await fetch(path);
      if (response.status !== 200)
        return null;

      return await response.json();
    } catch (TypeError) {
      return null;
    }
  }

  async fetch_data(...path) {
    return await this.fetch_json(path.length ? `/api/${path.join('/')}` : "/api");
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

  async _mail_row_fill(row, msg) {
    const self = this;

    if ((msg?.flags || []).indexOf("seen") < 0) {
      row.classList.add("unseen");
      row.querySelector("td.read input").checked = false;
    } else {
      row.classList.remove("unseen");
      row.querySelector("td.read input").checked = true;
    }

    if ((msg?.flags || []).indexOf("deleted") < 0) {
      row.classList.remove("is_deleted");
      row.querySelector("td.deleted input").checked = false;
    } else {
      row.classList.add("is_deleted");
      row.querySelector("td.deleted input").checked = true;
    }

    function content(selector, val) {
      row.querySelector(selector).innerHTML = (val || "").replace("<", "&lt;");
    }

    content(".from", msg.header?.from);
    content(".to", msg.header?.to);
    content(".subject", msg.header?.subject);
    content(".date", (new Date(msg.date)).toLocaleString());
  }

  async _mail_row_init(template, msg) {
    const self = this;

    const row = template.cloneNode(10);
    row.removeAttribute("id");
    row.classList.remove("hidden");

    row.querySelector(".read input").addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      self._mail_row_click(ev.target, "read");
    });

    row.querySelector(".deleted input").addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      self._mail_row_click(ev.target, "deleted");
    });

    row.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      self._mail_row_click(ev.target, "swap");
    });

    return row;
  }

  async _mail_row_click(element, type) {
    const self = this;

    let row = element;
    while (row && !row.uid) {
      row = row.parentElement;
    }

    if (!row.uid)
      return;


    switch (type) {
      case "swap":
        if (self.mail_selected)
          self.mail_selected.classList.remove("selected");

        self.mail_selected = row;
        self.mail_selected.classList.add("selected");
        await self.fetch_mail(row.uid);
        break;

      case "read":
        await self.set_flag("seen", element.checked ? "PUT" : "DELETE", row.uid);
        element.checked = !element.checked;
        break;

      case "deleted":
        await self.set_flag("deleted", element.checked ? "PUT" : "DELETE", row.uid);
        element.checked = !element.checked;
        break;
    }
  }

  async load_config() {
    const data = await this.fetch_json("/config");
    if (data !== null)
      this.config = data;
  }

  async upload_files(element) {
    const files = [];
    for (const file of element.files) {
      files.push({name: file.name, data: await file.text()});
    }

    await this.post_data(files, "upload", this.user_id, this.mailbox_id);

    // Clear the files
    element.value = null;
  }

  async fetch_accounts() {
    const self = this;
    const data = await this.fetch_data();
    if (data === null)
      return;

    for (const opt of this.users.options) {
      const user = data[opt.value];
      if (user !== undefined)
        delete data[opt.value];
      else
        opt.remove();
    }

    for (const uid in data)
      this.users.add(new Option(data[uid], uid));

    if (this.users.selectedIndex < 0) {
      this.users.selectedIndex = 0;
      if (this.users.options[0]) {
        await self.fetch_mailboxes(this.users.options[0].value);
      }
    } else {
      const selected = this.users.options[this.users.selectedIndex].value;
      if (this.user_id !== selected) {
        await self.fetch_mailboxes(selected);
      }
    }
  }

  async fetch_mailboxes(user_id) {
    const self = this;
    const data = await this.fetch_data(user_id);
    if (data === null)
      return;

    if (this.user_id !== user_id) {
      this.mailbox_id = null;
      this.mail_uid = null;
      this.mailbox.innerHTML = "";
      this.mailboxes.selectedIndex = -1;
    }

    this.user_id = user_id;

    for (const opt of this.mailboxes.options) {
      const name = data[opt.uid];
      if (name)
        data.splice(idx, 1);
      else
        opt.remove()
    }

    for (const uid in data) {
      this.mailboxes.add(new Option(data[uid], uid, true, this.mailbox_id === uid));
    }

    if (this.mailboxes.selectedIndex < 0) {
      this.mailboxes.selectedIndex = 0;
      if (this.mailboxes.options[0]) {
        await self.fetch_mailbox(this.mailboxes.options[0].value);
      }
    }
  }

  _display_mail(data) {
    document.querySelector("#header-from input").value = data?.header?.from || "";
    document.querySelector("#header-to input").value = data?.header?.to || "";
    document.querySelector("#header-cc input").value = data?.header?.cc || "";
    document.querySelector("#header-bcc input").value = data?.header?.bcc || "";
    document.querySelector("#header-subject input").value = data?.header?.subject || "";
    document.querySelector("#content textarea#source").value = data?.content || "";
    document.querySelector("#content textarea#plain").value = data?.body_plain || "";
    document.querySelector("#content iframe#html").srcdoc = data?.body_html || "";
  }

  async fetch_mailbox(mailbox_id) {
    const self = this;
    const data = await this.fetch_data(this.user_id, mailbox_id);
    if (data === null)
      return;

    if (this.mailbox_id !== mailbox_id) {
      this.mail_uid = null;
      this.mailbox.innerHTML = "";

      // on change of mailbox, do clear mail display
      this._display_mail(undefined);
    }

    this.mailbox_id = mailbox_id;
    const missing_msg = [];
    const uids = [];
    const lines = [];
    for (const msg of data) {
      uids.push(msg.uid);

      let found = false;
      for (const line of this.mailbox.children) {
        if (line.uid === msg.uid) {
          found = true;
          await self._mail_row_fill(line, msg);
          lines.push(line);
          break;
        }
      }

      if (!found)
        missing_msg.push(msg);
    }

    const template = document.querySelector("#mail-row-template");
    for (const msg of missing_msg) {
      const row = await self._mail_row_init(template, msg);

      row.uid = msg.uid;
      await self._mail_row_fill(row, msg);
      lines.push(row);
    }

    for (const line of lines) {
      if (uids.indexOf(line.uid) < 0 && line !== template)
        line.remove();
    }

    if (this.sort_asc) lines.reverse();
    for (const line of lines)
      this.mailbox.append(line);
  }

  async fetch_mail(uid) {
    const self = this;
    const data = await this.fetch_data(this.user_id, this.mailbox_id, uid);
    if (data === null)
      return;

    self.mail_uid = uid;

    self._display_mail(data);

    const dropdown = document.querySelector("#btn-dropdown div");
    dropdown.innerHTML = "";

    for (const attachment of data?.attachments || []) {
      const link = document.createElement("a");
      link.href = `/api/${this.user_id}/${this.mailbox_id}/${uid}/attachment/${attachment}`;
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

    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      row.remove();
    });

    row.append(key_td);
    row.append(value_td);
    row.append(btn_td);
    table.append(row);

    await this.visibility();
  }

  async reorder(asc) {
    this.sort_asc = asc;

    const element = document.querySelector("#mailbox .date .ordering");
    if (!element) return;

    if (this.sort_asc) {
      element.classList.add("asc");
      element.classList.remove("desc");
    } else {
      element.classList.add("desc");
      element.classList.remove("asc");
    }

    if (this.mailbox_id) await this.fetch_mailbox(this.mailbox_id);
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

    const attachments = [];
    for (const file of document.querySelector("#editor-attachments input").files) {
      attachments.push({
        size: file.size,
        mimetype: file.type,
        name: file.name,
        content: await file_to_base64(file),
      });
    }

    await this.post_data({
      header: headers,
      body: document.querySelector("#editor-content textarea").value,
      attachments: attachments,
    }, this.user_id, this.mailbox_id);

    document.querySelector("#editor").classList.add("hidden");
    await this.reset_editor();
  }

  async reply_mail() {
    if (!this.mailbox_id || !this.mail_uid)
      return;

    const data = await this.fetch_data(
      this.user_id, this.mailbox_id, this.mail_uid, "reply"
    );
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
    document.querySelector("#editor-attachments input").value = "";
  }

  async initialize() {
    const self = this;
    this.mailboxes.addEventListener("change", (ev) => {
      ev.preventDefault();
      self.fetch_mailbox(ev.target.value);
    });
    document.getElementById("btn-html").addEventListener("click", (ev) => {
      ev.preventDefault();
      self.content_mode = "html";
      self.visibility();
    });
    document.getElementById("btn-plain").addEventListener("click", (ev) => {
      ev.preventDefault();
      self.content_mode = "plain";
      self.visibility();
    });
    document.getElementById("btn-source").addEventListener("click", (ev) => {
      ev.preventDefault();
      self.content_mode = "source";
      self.visibility();
    });
    document.getElementById("btn-new").addEventListener("click", (ev) => {
      ev.preventDefault();
      document.querySelector("#editor").classList.remove("hidden");
    });
    document.getElementById("btn-cancel").addEventListener("click", (ev) => {
      ev.preventDefault();
      document.querySelector("#editor").classList.add("hidden");
      self.reset_editor();
    });
    document.getElementById("btn-send").addEventListener("click", (ev) => {
      ev.preventDefault();
      self.send_mail();
    });
    document.getElementById("btn-reply").addEventListener("click", (ev) => {
      ev.preventDefault();
      self.reply_mail();
    });
    document.getElementById("btn-advanced").addEventListener("click", (ev) => {
      ev.preventDefault();
      self.editor_mode = (self.editor_mode === "simple") ? "advanced" : "simple";
      self.visibility();
    });
    document.getElementById("btn-add-header").addEventListener("click", (ev) => {
      ev.preventDefault();
      self.add_header();
    });
    document.querySelector("#color-scheme").addEventListener("click", (ev) => {
      ev.preventDefault();
      self.swap_theme();
    });
    document.querySelector("#uploader input").addEventListener("change", (ev) => {
      ev.preventDefault();
      self.upload_files(ev.target);
    });
    document.querySelector("#mailbox .date").addEventListener("click", (ev) => {
      ev.preventDefault();
      self.reorder(!self.sort_asc);
    });

    await this.load_config();
    await this.visibility();
    await this.idle();
  }
}
