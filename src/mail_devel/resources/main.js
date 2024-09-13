function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

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
    this.accounts = document.getElementById("accounts");
    this.connection = document.querySelector("#connection input[type=checkbox]");
    this.mailboxes = document.querySelector("#nav #mailboxes");
    this.mailbox = document.querySelector("#mailbox table tbody");
    this.wrapper = document.querySelector("#wrapper");
    this.fixed_headers = ["from", "to", "cc", "bcc", "subject"];
    this.account_name = null;
    this.mailbox_name = null;
    this.mail_uid = null;
    this.mail_selected = null;
    this.content_mode = "html";
    this.editor_mode = "simple";
    this.config = {};

    this.reset_drag();

    this.connect_socket();

    this.load_color_scheme();

    this.apply_drag(
      parseInt(localStorage.getItem("drag-nav")),
      parseInt(localStorage.getItem("drag-mailbox")),
    );

    this.reorder(localStorage.getItem("sort") === "asc");
  }

  async load_color_scheme() {
    const toggle = document.querySelector("#color-scheme input");
    const scheme = localStorage.getItem("color-scheme");
    if (scheme)
      toggle.checked = scheme === "dark";
    else {
      toggle.checked = (
        document.documentElement.classList.contains("dark") ||
        window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      );

      localStorage.setItem("color-scheme", toggle.checked ? "dark" : "light");
    }

    await this.apply_color_scheme();
  }

  async apply_color_scheme() {
    const toggle = document.querySelector("#color-scheme input");
    if (toggle.checked) {
      localStorage.setItem("color-scheme", "dark");
      document.documentElement.classList.add("dark");
      document.documentElement.classList.remove("light");
    } else {
      localStorage.setItem("color-scheme", "light");
      document.documentElement.classList.add("light");
      document.documentElement.classList.remove("dark");
    }
  }

  async visibility() {
    vis("#btn-html", this.content_mode !== "html");
    vis("#btn-plain", this.content_mode !== "plain");
    vis("#btn-source", this.content_mode !== "source");
    vis("#mail-content iframe#html", this.content_mode === "html");
    vis("#mail-content textarea#plain", this.content_mode === "plain");
    vis("#mail-content textarea#source", this.content_mode === "source");
    vis("#editor .header .extra", this.editor_mode === "advanced");
    vis("#editor #btn-add-header", this.editor_mode === "advanced");

    document.getElementById("btn-advanced").innerText = (
      `${this.editor_mode === "simple" ? "Advanced" : "Simple"} View`
    );
  }

  async idle() {
    const self = this;

    await this.load_accounts();

    if (this.account_name)
      await this.load_mailboxes();

    if (this.mailbox_name)
      await this.load_mailbox();

    setTimeout(() => {self.idle();}, 2000);
  }

  connect_socket() {
    if (this.socket)
      return;

    const proto = (window.location.protocol === "https:") ? "wss:" : "ws:";
    const url = `${proto}//${window.location.host}${window.location.pathname}websocket`;
    this.socket = new WebSocket(url);

    const self = this;
    this.socket.onmessage = this.on_socket_message.bind(this);
    this.socket.onclose = this.on_socket_close.bind(this);
    this.socket.onerror = this.on_socket_error.bind(this);
    this.socket.onopen = this.on_socket_open.bind(this);
  }

  close_socket() {
    if (this.socket)
      this.socket.close();

    this.socket = null;
  }

  async on_socket_message(event) {
    /* Dispatch the data to the correct handler */
    const data = JSON.parse(event.data);
    if (data.command) {
      const func = this[`on_${data.command}`];
      if (typeof func === "function") {
        func.call(this, data.data);
      }
    }
  }

  async on_socket_open(event) {
    await this.load_config();
  }

  async on_socket_close(event) {
    if (!event.wasClean)
      console.log("Websocket connection died");

    this.socket = null;
    if (this.connection.checked)
      setTimeout(1000, this.connect_socket.bind(this));
  }

  async on_socket_error(event) {
    console.error("Websocket error", event);
  }

  async socket_send(data) {
    if (this.socket && this.socket.readyState)
      this.socket.send(JSON.stringify(data));
  }

  async load_config() {
    await this.socket_send({command: "config"});
  }

  async on_config(data) {
    this.config = data;

    vis("#accounts", Boolean(this.config?.multi_user));
    document.querySelector("#version").innerHTML = this.config?.version || "";
  }

  async flag_mail(flag, method, uid = null) {
    const mail_uid = uid || this.mail_uid;
    if (this.mailbox_name && mail_uid) {
      await this.socket_send(
        {
          command: "flag_mail",
          account: this.account_name,
          mailbox: this.mailbox_name,
          uid: uid,
          method: method,
          flag: flag
        }
      );
    }
  }

  async upload_files(element) {
    const files = [];
    for (const file of element.files) {
      files.push({name: file.name, data: await file.text()});
    }

    await this.socket_send(
      {
        command: "upload_mails",
        account: this.account_name,
        mailbox: this.mailbox_name,
        mails: files,
      },
    );

    // Clear the files
    element.value = null;
  }

  async load_accounts() {
    await this.socket_send({command: "list_accounts"});
  }

  async on_list_accounts(data) {
    const self = this;
    const accounts = data.accounts;
    if (!accounts)
      return;

    for (const opt of this.accounts.options) {
      const idx = accounts.indexOf(opt.value);
      if (idx < 0)
        opt.remove();
      else
        accounts.splice(idx, 1);
    }

    for (const account of accounts)
      this.accounts.add(new Option(account, account));

    if (this.accounts.selectedIndex < 0) {
      this.accounts.selectedIndex = 0;
      if (this.accounts.options[0]) {
        await self.load_mailboxes(this.accounts.options[0].value);
      }
    } else {
      const selected = this.accounts.options[this.accounts.selectedIndex].value;
      if (this.account_name !== selected) {
        await self.load_mailboxes(selected);
      }
    }
  }

  async load_mailboxes(account_name) {
    if (!account_name)
      account_name = this.account_name;

    if (account_name)
      await this.socket_send({command: "list_mailboxes", account: account_name});
  }

  async on_list_mailboxes(data) {
    const self = this;
    const account_name = data.account;

    if (this.account_name !== account_name) {
      this.mailbox_name = null;
      this.mail_uid = null;
      this.mailbox.innerHTML = "";
      this.mailboxes.selectedIndex = -1;
    }

    this.account_name = account_name;

    const tmp = [];
    for (const opt of this.mailboxes.options) {
      const idx = data.mailboxes.indexOf(opt.value);
      if (idx >= 0) {
        tmp.push(opt);
        data.mailboxes.splice(idx, 1);
      }
    }

    for (const mailbox of data.mailboxes) {
      const opt = new Option(mailbox, mailbox, true, this.mailbox_name === mailbox);
      tmp.push(opt);

      opt.addEventListener("dragover", (ev) => {ev.preventDefault();});
      opt.addEventListener("drop", self.ondrop_mailbox.bind(self));
    }

    // Sort
    tmp.sort((a, b) => {
      if (a.value === "INBOX")
        return -1
      else if (b.value === "INBOX")
        return 1;
      return a.value.localeCompare(b.value);
    });

    while (this.mailboxes.options.length)
      this.mailboxes.options.remove(0);

    for (const opt of tmp)
      this.mailboxes.options.add(opt);

    if (this.mailboxes.selectedIndex < 0) {
      this.mailboxes.selectedIndex = 0;
      if (this.mailboxes.options[0]) {
        await self.load_mailbox(this.mailboxes.options[0].value);
      }
    }
  }

  async load_mailbox(mailbox_name) {
    if (!mailbox_name)
      mailbox_name = this.mailbox_name;

    if (mailbox_name)
      await this.socket_send(
        {command: "list_mails", account: this.account_name, mailbox: mailbox_name}
      );
  }

  async on_list_mails(data) {
    const mailbox_name = data.mailbox;
    const mails = data.mails;
    if (!mailbox_name)
      return;

    if (this.mailbox_name !== mailbox_name) {
      this.mail_uid = null;
      this.mailbox.innerHTML = "";

      // on change of mailbox, do clear mail display
      this._display_mail(undefined);
    }

    this.mailbox_name = mailbox_name;
    const missing_msg = [];
    const uids = [];
    const lines = [];
    const self = this;
    for (const msg of mails) {
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
      row.addEventListener("dragstart", this.ondrag_mail.bind(this));
      await self._mail_row_fill(row, msg);
      lines.push(row);
    }

    for (const line of this.mailbox.children) {
      if (uids.indexOf(line.uid) < 0 && line !== template)
        line.remove();
    }

    if (this.sort_asc) lines.reverse();

    for (const line of lines)
      this.mailbox.append(line);
  }

  async load_mail(uid) {
    await this.socket_send(
      {
        "command": "get_mail",
        "account": this.account_name,
        "mailbox": this.mailbox_name,
        "uid": uid,
      }
    );
  }

  async on_get_mail(data) {
    const self = this;
    const uid = data.uid;
    const mail = data.mail;
    if (!uid || !mail)
      return;

    self.mail_uid = uid;
    self._display_mail(mail);

    const dropdown = document.querySelector("#btn-dropdown div");
    dropdown.innerHTML = "";

    for (const attachment of mail?.attachments || []) {
      const link = document.createElement("a");
      link.href = attachment.url;
      link.innerHTML = attachment.name;
      dropdown.append(link);
    }

    if (!mail?.body_html && self.content_mode === "html")
      self.content_mode = "plain";

    await self.visibility();
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
    for (const file of document.querySelector("#editor .attachments input").files) {
      attachments.push({
        size: file.size,
        mimetype: file.type,
        name: file.name,
        content: await file_to_base64(file),
      });
    }

    await this.socket_send({
      command: "send_mail",
      account: this.account_name,
      mailbox: this.mailbox_name,
      mail: {
        header: headers,
        body: document.querySelector("#editor .content textarea").value,
        attachments: attachments,
      },
    });

    document.querySelector("#editor").classList.add("hidden");
    await this.reset_editor();
  }

  async on_send_mail() {
    await this.load_mailbox();
  }

  async load_random_mail() {
    if (!this.account_name || !this.mailbox_name)
      return;

    await this.socket_send(
      {
        command: "random_mail",
        account: this.account_name,
        mailbox: this.mailbox_name,
      }
    );
  }

  async on_random_mail(data) {
    await this.reset_editor(data?.mail?.header || {}, data?.mail?.body_plain || "");
    document.querySelector("#editor").classList.remove("hidden");
  }

  async load_reply_mail() {
    if (!this.mailbox_name || !this.mail_uid)
      return;

    await this.socket_send(
      {
        command: "reply_mail",
        account: this.account_name,
        mailbox: this.mailbox_name,
        uid: this.mail_uid,
      }
    );
  }

  async on_reply_mail(data) {
    await this.reset_editor(data?.mail?.header || {});
    document.querySelector("#editor").classList.remove("hidden");
  }

  async _mail_row_fill(row, msg) {
    const self = this;

    let ele = row.querySelector("td.flags .read input");
    if ((msg?.flags || []).indexOf("seen") < 0) {
      row.classList.add("unseen");
      ele.checked = false;
    } else {
      row.classList.remove("unseen");
      ele.checked = true;
    }

    ele = row.querySelector("td.flags .deleted input");
    if ((msg?.flags || []).indexOf("deleted") < 0) {
      row.classList.remove("deleted");
      ele.checked = false;
    } else {
      row.classList.add("deleted");
      ele.checked = true;
    }

    function content(selector, val) {
      row.querySelector(selector).innerHTML = (val || "").replace("<", "&lt;");
    }

    content(".from", msg.header?.from);
    content(".to", msg.header?.to);
    content(".subject", msg.header?.subject);
    const dt = new Date(msg.date);
    row.querySelector(".date").innerHTML = `${dt.toLocaleDateString()}<br />${dt.toLocaleTimeString()}`;
  }

  async _mail_row_init(template, msg) {
    const self = this;

    const row = template.cloneNode(10);
    row.removeAttribute("id");
    row.classList.remove("hidden");

    row.querySelector("td.flags .read").addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      self._mail_row_click(ev.target, "seen");
    });

    row.querySelector("td.flags .deleted").addEventListener("click", (ev) => {
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
        await self.load_mail(row.uid);
        break;

      case "seen": case "deleted":
        await self.flag_mail(type, element.checked ? "set" : "unset", row.uid);
        element.checked = !element.checked;
        break;
    }
  }

  _display_mail(data) {
    document.querySelector("#header-from input").value = data?.header?.from || "";
    document.querySelector("#header-to input").value = data?.header?.to || "";
    document.querySelector("#header-cc input").value = data?.header?.cc || "";
    document.querySelector("#header-bcc input").value = data?.header?.bcc || "";
    document.querySelector("#header-subject input").value = data?.header?.subject || "";
    document.querySelector("#mail-content textarea#source").value = data?.content || "";
    document.querySelector("#mail-content textarea#plain").value = data?.body_plain || "";
    document.querySelector("#mail-content iframe#html").srcdoc = data?.body_html || "";
  }

  async add_header(key = null, value = null) {
    const table = document.querySelector("#editor .header");
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

    if (this.mailbox_name) await this.load_mailbox(this.mailbox_name);
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

    document.querySelector("#editor .content textarea").value = body || "";
    document.querySelector("#editor .attachments input").value = "";
  }

  async initialize() {
    const self = this;

    this.mailboxes.addEventListener("change", (ev) => {
      ev.preventDefault();
      self.load_mailbox(ev.target.value);
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
      document.querySelector("#mailbox-control").classList.add("hidden");
    });

    document.getElementById("btn-random").addEventListener("click", (ev) => {
      ev.preventDefault();
      self.load_random_mail();
    });

    document.querySelector("#editor #btn-cancel").addEventListener("click", (ev) => {
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
      self.load_reply_mail();
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
      const toggle = document.querySelector("#color-scheme input");
      toggle.checked = !toggle.checked;
      self.apply_color_scheme();
    });

    document.querySelector("#connection").addEventListener("click", (ev) => {
      ev.preventDefault();

      const toggle = document.querySelector("#connection input");
      if (toggle.checked)
        self.close_socket();
      else
        self.connect_socket();

      toggle.checked = !toggle.checked;
    });

    document.querySelector("#uploader input").addEventListener("change", (ev) => {
      ev.preventDefault();
      self.upload_files(ev.target);
    });

    document.querySelector("#mailbox .date").addEventListener("click", (ev) => {
      ev.preventDefault();
      localStorage.setItem("sort", self.sort_asc ? "desc" : "asc");
      self.reorder(!self.sort_asc);
    });

    document.querySelector("#nav-dragbar").addEventListener("mousedown", (ev) => {
      ev.preventDefault();
      self.drag.nav = true;
      self.wrapper.style.cursor = "ew-resize";
    });

    document.querySelector("#mailbox-dragbar").addEventListener("mousedown", (ev) => {
      ev.preventDefault();
      self.drag.mailbox = true;
      self.wrapper.style.cursor = "ns-resize";
    });

    this.wrapper.addEventListener("mouseup", self.reset_drag.bind(self));
    this.wrapper.addEventListener("mousemove", (ev) => {
      ev.preventDefault();
      self.ondrag(ev);
    });

    document.querySelector("#btn-mailbox-manage").addEventListener(
      "click", () => {
        document.querySelector("#editor").classList.add("hidden");
        self.visibility_mailbox_control();
      }
    );

    document.querySelector("#mailbox-control #btn-cancel").addEventListener("click", (ev) => {
      ev.preventDefault();
      self.visibility_mailbox_control(true);
    });

    document.querySelector("#btn-add-folder").addEventListener("click", (ev) => {
      ev.preventDefault();
      self.add_mailbox(false);
    });
    document.querySelector("#btn-add-sub-folder").addEventListener("click", (ev) => {
      ev.preventDefault();
      self.add_mailbox(true);
    });
    document.querySelector("#btn-del-folder").addEventListener("click", (ev) => {
      ev.preventDefault();
      self.delete_mailbox();
    });

    await this.visibility();
    await this.idle();
  }

  async visibility_mailbox_control(force_close=false) {
    const control = document.querySelector("#mailbox-control");
    if (force_close)
      control.classList.add("hidden")
    else
      control.classList.toggle("hidden");

    const icon = document.querySelector("#btn-mailbox-manage .icon");
    if (control.classList.contains("hidden"))
      icon.classList.remove("open");
    else
      icon.classList.add("open");

    this.reset_mailbox_control();
  }

  async add_mailbox(subfolder=false) {
    const input = document.querySelector("#mailbox-name");
    if (input.value)
      await this.socket_send(
        {
          command: "add_mailbox",
          account: this.account_name,
          parent: subfolder ? this.mailbox_name : false,
          name: input.value,
        }
      );
  }

  async delete_mailbox() {
    await this.socket_send(
      {
        command: "delete_mailbox",
        account: this.account_name,
        name: this.mailbox_name,
      }
    );
  }

  async reset_mailbox_control() {
    const input = document.querySelector("#mailbox-name");
    input.value = "";
  }

  reset_drag() {
    this.drag = {nav: false, mailbox: false};
    self.wrapper.style.cursor = "auto";
  }

  apply_drag(nav=null, mailbox=null) {
    if (nav) {
      const pos = clamp(nav, 250, 300);
      const dragbar = document.querySelector("#nav-dragbar");
      const sizes = [
        `${pos}px`,
        `${dragbar.clientWidth}px`,
        "auto",
      ];
      this.wrapper.style.gridTemplateColumns = sizes.join(" ");

      const control = document.querySelector("#mailbox-control");
      control.style.left = pos + "px";
      control.style.top = this.mailboxes.offsetTop + "px";
    }

    if (mailbox) {
      const dragbar = document.querySelector("#mailbox-dragbar");
      const header = document.querySelector("#mail-header");
      const max_height = this.wrapper.clientHeight - header.clientHeight - dragbar.clientHeight;
      const pos = clamp(mailbox, 50, max_height);
      const sizes = [
        `${pos}px`,
        `${dragbar.clientHeight}px`,
        `${header.clientHeight}px`,
        "auto",
      ];

      this.wrapper.style.gridTemplateRows = sizes.join(" ");
    }
  }

  ondrag(ev) {
    if (this.drag.nav) {
      localStorage.setItem("drag-nav", event.clientX);
      this.apply_drag(event.clientX, null);
    }

    if (this.drag.mailbox) {
      localStorage.setItem("drag-mailbox", event.clientY);
      this.apply_drag(null, event.clientY);
    }
  }

  async ondrag_mail(ev) {
    ev.dataTransfer.setData("text", ev.target.uid);
  }

  async ondrop_mailbox(ev) {
    ev.preventDefault();
    const mail_uid = ev.dataTransfer.getData("text");
    const mailbox_name = ev.target.value;
    if (mail_uid && mailbox_name)
      await this.socket_send(
        {
            command: "move_mail",
            account: this.account_name,
            mailbox_from: this.mailbox_name,
            mailbox_to: mailbox_name,
            mail_uid: parseInt(mail_uid),
        }
      );
  }
}
