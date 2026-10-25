function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function file_to_base64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.readAsDataURL(file);
    reader.onload = () => resolve(reader.result.replace(/.*,/, ""));
    reader.onerror = reject;
  });
}

function stop_event(ev) {
  ev.preventDefault();
  ev.stopPropagation();
}

function vis(selector, visible) {
  const elements = document.querySelectorAll(selector);
  if (!elements)
    return

  for (const element of elements)
    element.classList.toggle("hidden", !visible);
}

function checked(selector, checked) {
  const elements = document.querySelectorAll(selector);
  if (!elements)
    return

  for (const element of elements)
    element.classList.toggle("checked", checked);
}

class MailClient {
  constructor() {
    this.fixed_headers = ["date", "from", "to", "cc", "bcc", "subject"];

    this.connection = true;
    this.color_scheme = true;

    this.account_name = null;
    this.mailbox_name = null;
    this.mail_uid = null;
    this.mail_selected = null;
    this.content_mode = "html";
    this.editor_mode = "simple";
    this.config = {};

    this.reset_drag();
    this.reset_editor();

    this.connect_socket();

    this.load_color_scheme();

    this.apply_drag(
      parseInt(localStorage.getItem("drag-nav")),
      parseInt(localStorage.getItem("drag-mailbox")),
    );

    this.reorder(localStorage.getItem("sort") === "asc");
  }

  async load_color_scheme() {
    const scheme = localStorage.getItem("color-scheme");
    if (scheme)
      this.color_scheme = scheme === "dark";
    else {
      this.color_scheme = (
        document.documentElement.classList.contains("dark") ||
        window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      );

      localStorage.setItem("color-scheme", this.color_scheme ? "dark" : "light");
    }

    await this.apply_color_scheme();
  }

  async apply_color_scheme() {
    localStorage.setItem("color-scheme", this.color_scheme ? "dark": "light");
    document.documentElement.classList.toggle("dark", this.color_scheme);
    document.documentElement.classList.toggle("light", !this.color_scheme);

    const ele = document.querySelector("#btn-color-scheme *");
    ele.classList.toggle("fa-moon", this.color_scheme);
    ele.classList.toggle("fa-sun", !this.color_scheme);
    ele.title = `Switch to ${this.color_scheme ? "light" : "dark"} mode`;
  }

  async apply_connection() {
    const ele = document.querySelector("#btn-connection *");
    ele.classList.toggle("fa-repeat", this.connection);
    ele.classList.toggle("fa-pause", !this.connection);
    ele.title = `${this.connection ? "Disable" : "Enable"} connection`;
  }

  async visibility() {
    const simple_mode = this.editor_mode === "simple";

    checked("#btn-html", this.content_mode === "html");
    checked("#btn-plain", this.content_mode === "plain");
    checked("#btn-source", this.content_mode === "source");

    vis("#mail-content iframe#html", this.content_mode === "html");
    vis("#mail-content textarea#plain", this.content_mode === "plain");
    vis("#mail-content textarea#source", this.content_mode === "source");
    vis("#editor .header .extra", this.editor_mode === "advanced");
    vis("#editor .simple", simple_mode);
    vis("#editor .advanced", !simple_mode);

    const ele = document.querySelector("#btn-advanced *");
    ele.classList.toggle("fa-eye-slash", simple_mode);
    ele.classList.toggle("fa-eye", !simple_mode);
    ele.parentNode.title = `Show ${simple_mode ? "Advanced" : "Simple"} View`;
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

    this.apply_connection();
  }

  close_socket() {
    if (this.socket)
      this.socket.close();

    this.socket = null;
    this.apply_connection();
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
    if (this.connection)
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
    const accounts = document.querySelector("#accounts");

    const self = this;
    if (!data.accounts)
      return;

    for (const opt of accounts.options) {
      const idx = data.accounts.indexOf(opt.value);
      if (idx < 0)
        opt.remove();
      else
        data.accounts.splice(idx, 1);
    }

    for (const account of data.accounts)
      accounts.add(new Option(account, account));

    if (accounts.selectedIndex < 0) {
      accounts.selectedIndex = 0;
      if (accounts.options[0]) {
        await self.load_mailboxes(accounts.options[0].value);
      }
    } else {
      const selected = accounts.options[accounts.selectedIndex].value;
      if (this.account_name !== selected) {
        await self.load_mailboxes(selected);
      }
    }
  }

  async load_mailboxes(account_name) {
    if (!account_name)
      account_name = this.account_name;

    if (account_name && this.connection)
      await this.socket_send({command: "list_mailboxes", account: account_name});
  }

  async on_list_mailboxes(data) {
    const self = this;
    const account_name = data.account;
    const mailboxes = document.querySelector("#mailboxes");
    const mailbox = document.querySelector("#mailbox table tbody");
    let options = mailboxes.querySelectorAll("div.option") || [];

    if (this.account_name !== account_name) {
      this.mailbox_name = null;
      this.mail_uid = null;
      mailbox.innerHTML = "";
    }

    this.account_name = account_name;

    // Generate enough options
    const template = document.querySelector("#template-mailbox");
    for (let i = options.length; i < data.mailboxes.length; i++) {
      const option = document.importNode(template.content, true).querySelector("div.option");
      mailboxes.append(option);

      option.addEventListener("dragover", (ev) => {consume(ev)});
      option.addEventListener("drop", self.ondrop_mailbox.bind(self));
      option.addEventListener("click", (ev) => {
        stop_event(ev);
        if (option.value)
          self.load_mailbox(option.value);
      });
      option.querySelector(".btn-del-folder").addEventListener("click", (ev) => {
        stop_event(ev);
        if (option.value)
          self.delete_mailbox(option.value);
      });
    }

    for (let i = data.mailboxes.length; i < options.length; i++) {
      options[i].remove();
    }

    // Query again after the creation/deletion
    options = mailboxes.querySelectorAll("div.option");

    // Fill the options and set up event listeners
    for (const i in data.mailboxes) {
      const mailbox = data.mailboxes[i];
      const option = options[i];

      // If no mailbox is selected the first gets used
      if (!this.mailbox_name) {
        this.mailbox_name = mailbox;
      }
      option.value = mailbox;
      option.querySelector(".name").innerHTML = mailbox;
    }

    self.apply_mailboxes_selection();
  }

  async apply_mailboxes_selection() {
    for (const option of document.querySelectorAll("#mailboxes div.option")) {
      option.classList.toggle("selected", this.mailbox_name === option.value);
    }
  }

  async load_mailbox(mailbox_name) {
    if (!mailbox_name)
      mailbox_name = this.mailbox_name;

    if (mailbox_name && this.connection)
      await this.socket_send(
        {command: "list_mails", account: this.account_name, mailbox: mailbox_name}
      );
  }

  async on_list_mails(data) {
    const mailbox_name = data.mailbox;
    const mails = data.mails;
    if (!mailbox_name)
      return;

    const mailbox = document.querySelector("#mailbox table tbody");
    if (this.mailbox_name !== mailbox_name) {
      this.mail_uid = null;
      mailbox.innerHTML = "";

      // on change of mailbox, do clear mail display
      this._display_mail(undefined);
    }


    this.mailbox_name = mailbox_name;
    await this.apply_mailboxes_selection();

    // Generate enough rows
    const template = document.querySelector("#template-mail-row");
    let rows = mailbox.querySelectorAll("tr");
    for (let i = rows.length; i < mails.length; i++)
      mailbox.append(await this._mail_row_init(template));

    for (let i = mails.length; i < rows.length; i++)
      rows[i].remove();

    // Fill in the rows
    if (this.sort_asc) mails.reverse();

    rows = mailbox.querySelectorAll("tr");
    for (let i = 0; i < mails.length; i++) {
      await this._mail_row_fill(rows[i], mails[i]);
    }
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
    let headers = {};
    if (this.editor_mode === "simple") {
      for (const key of this.fixed_headers)
        headers[key] = document.querySelector(`input#editor-${key}`).value;
    } else {
      headers = document.querySelector("#editor-advanced").value;
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

  async on_mail_datetime(data) {
    // The datetime string is created by the backend
    if (data.datetime) {
      document.querySelector("input#editor-date").value = data.datetime;

      const advanced = document.querySelector("textarea#editor-advanced");
      const line = `date: ${data.datetime}\n`;
      const regex = /^date:.*$/gmi;
      if (advanced.value.match(regex))
        advanced.value = advanced.value.replace(regex, line);
      else
        advanced.value += line;

      advanced.value = advanced.value.replaceAll(/\n{2,}/g, "\n").trim();
    }
  }

  async _mail_row_fill(row, msg) {
    const self = this;

    row.classList.add("no-transition");

    row.uid = msg.uid;
    let ele = row.querySelector("td.flags .read");
    let checked = (msg?.flags || []).indexOf("seen") >= 0;

    // Handle the read flag
    ele.querySelector("input").checked = checked;
    row.classList.toggle("unseen", !checked);
    ele.classList.toggle("fa-envelope-open", checked);
    ele.classList.toggle("fa-envelope", !checked);

    // Handle the deleted flag
    ele = row.querySelector("td.flags .deleted");
    checked = (msg?.flags || []).indexOf("deleted") >= 0;
    ele.querySelector("input").checked = checked;
    row.classList.toggle("deleted", checked);

    function content(selector, val) {
      row.querySelector(selector).innerHTML = (val || "").replace("<", "&lt;");
    }

    // Enter the content of the mail
    content(".from", msg.header?.from);
    content(".subject", msg.header?.subject);

    // Enter the date
    const dt_ele = row.querySelector(".date");
    const dt = new Date(msg.header?.date || msg.date);
    const diff = (new Date() - dt) / 1000;

    dt_ele.title = `${dt.toLocaleDateString()} ${dt.toLocaleTimeString()}`;

    // Shorten the time for readability
    if (diff < 60) {
      dt_ele.innerHTML = "just now";
    } else if (diff < 60 * 60) {
      dt_ele.innerHTML = `${Math.floor(diff / 60)} min ago`;
    } else if (diff < 24 * 60 * 60) {
      dt_ele.innerHTML = dt.toLocaleTimeString();
    } else {
      dt_ele.innerHTML = dt.toLocaleDateString();
    }

    row.classList.remove("no-transition");
  }

  async _mail_row_init(template) {
    const self = this;

    const tr = document.importNode(template.content, true).querySelector("tr");

    // Install the event listeners
    tr.addEventListener("click", (ev) => {
      stop_event(ev);
      self._mail_row_click(ev.target, "swap");
    });
    tr.querySelector("td.flags .read").addEventListener("click", (ev) => {
      stop_event(ev);
      self._mail_row_click(ev.target, "seen");
    });
    tr.querySelector("td.flags .deleted").addEventListener("click", (ev) => {
      stop_event(ev);
      self._mail_row_click(ev.target, "deleted");
    });
    tr.addEventListener("dragstart", this.ondrag_mail.bind(this));

    return tr;
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
    document.querySelector("#header-date input").value = data?.header?.date || "";
    document.querySelector("#header-from input").value = data?.header?.from || "";
    document.querySelector("#header-to input").value = data?.header?.to || "";
    document.querySelector("#header-cc input").value = data?.header?.cc || "";
    document.querySelector("#header-bcc input").value = data?.header?.bcc || "";
    document.querySelector("#header-subject input").value = data?.header?.subject || "";
    document.querySelector("#mail-content textarea#source").value = data?.content || "";
    document.querySelector("#mail-content textarea#plain").value = data?.body_plain || "";
    document.querySelector("#mail-content iframe#html").srcdoc = data?.body_html || "";
  }

  async reorder(asc) {
    this.sort_asc = asc;

    const element = document.querySelector("#mailbox .date .ordering");
    if (!element) return;

    element.classList.toggle("fa-sort-down", this.sort_asc);
    element.classList.toggle("fa-sort-up", !this.sort_asc);

    if (this.mailbox_name) await this.load_mailbox(this.mailbox_name);
  }

  async reset_editor(header = null, body = null) {
    let advanced = "";
    for (const key in header || []) {
      advanced += `${key}: ${header[key]}\n`;
    }

    for (const key of this.fixed_headers) {
      const element = document.querySelector(`input#editor-${key}`);
      element.value = (header && header[key]) ? header[key] : "";

      if (!header || !header[key])
        advanced += `${key}:\n`;
    }

    document.querySelector("#editor-advanced").value = advanced;
    document.querySelector("#editor .content textarea").value = body || "";
    document.querySelector("#editor .attachments input").value = "";
  }

  async initialize() {
    const self = this;

    document.querySelector("#btn-html").addEventListener("click", (ev) => {
      stop_event(ev);
      self.content_mode = "html";
      self.visibility();
    });

    document.querySelector("#btn-plain").addEventListener("click", (ev) => {
      stop_event(ev);
      self.content_mode = "plain";
      self.visibility();
    });

    document.querySelector("#btn-source").addEventListener("click", (ev) => {
      stop_event(ev);
      self.content_mode = "source";
      self.visibility();
    });

    document.querySelector("#btn-new").addEventListener("click", async (ev) => {
      stop_event(ev);
      document.querySelector("#editor").classList.remove("hidden");

      await this.socket_send({"command": "format_datetime"});
    });

    document.querySelector("#btn-random").addEventListener("click", (ev) => {
      stop_event(ev);
      self.load_random_mail();
    });

    document.querySelector("#editor #btn-cancel").addEventListener("click", (ev) => {
      stop_event(ev);
      document.querySelector("#editor").classList.add("hidden");
      self.reset_editor();
    });

    document.querySelector("#btn-send").addEventListener("click", (ev) => {
      stop_event(ev);
      self.send_mail();
    });

    document.querySelector("#btn-reply").addEventListener("click", (ev) => {
      stop_event(ev);
      self.load_reply_mail();
    });

    document.querySelector("#btn-advanced").addEventListener("click", (ev) => {
      stop_event(ev);
      self.editor_mode = (self.editor_mode === "simple") ? "advanced" : "simple";
      self.visibility();
    });

    document.querySelector("#btn-color-scheme").addEventListener("click", (ev) => {
      stop_event(ev);
      self.color_scheme = !self.color_scheme;
      self.apply_color_scheme();
    });

    document.querySelector("#btn-connection").addEventListener("click", (ev) => {
      stop_event(ev);
      this.connection = !this.connection;
      this.apply_connection();
    });

    document.querySelector("#uploader input").addEventListener("change", (ev) => {
      stop_event(ev);
      self.upload_files(ev.target);
    });

    document.querySelector("#mailbox .date").addEventListener("click", (ev) => {
      stop_event(ev);
      localStorage.setItem("sort", self.sort_asc ? "desc" : "asc");
      self.reorder(!self.sort_asc);
    });

    document.querySelector("#mailbox-dragbar").addEventListener("mousedown", (ev) => {
      stop_event(ev);
      self.drag.mailbox = true;
      self.wrapper.style.cursor = "ns-resize";
    });

    const wrapper = document.querySelector("#wrapper");
    wrapper.addEventListener("mouseup", (ev) => {
      stop_event(ev);
      self.reset_drag();
    });
    wrapper.addEventListener("mousemove", (ev) => {
      stop_event(ev);
      self.ondrag(ev);
    });

    document.querySelector("#mailbox-name").addEventListener("input", (ev) => {
      if (ev.target.value)
        ev.target.classList.remove("required");
    });
    document.querySelector("#btn-add-folder").addEventListener("click", (ev) => {
      stop_event(ev);
      self.add_mailbox(false);
    });
    document.querySelector("#btn-add-sub-folder").addEventListener("click", (ev) => {
      stop_event(ev);
      self.add_mailbox(true);
    });

    await this.visibility();
    await this.idle();
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
    else {
      input.classList.add("required");
    }
  }

  async delete_mailbox(mailbox) {
    await this.socket_send(
      {
        command: "delete_mailbox",
        account: this.account_name,
        name: mailbox,
      }
    );
  }

  reset_drag() {
    this.drag = {mailbox: false};
    self.wrapper.style.cursor = "auto";
  }

  apply_drag(mailbox=null) {
    if (mailbox) {
      const dragbar = document.querySelector("#mailbox-dragbar");
      const header = document.querySelector("#mail-header");
      const wrapper = document.querySelector("#wrapper");
      const max_height = wrapper.clientHeight - header.clientHeight - dragbar.clientHeight;
      const pos = clamp(mailbox, 50, max_height);
      const sizes = [
        `${pos}px`,
        `${dragbar.clientHeight}px`,
        `${header.clientHeight}px`,
        "auto",
      ];

      wrapper.style.gridTemplateRows = sizes.join(" ");
    }
  }

  ondrag(ev) {
    if (this.drag.mailbox) {
      localStorage.setItem("drag-mailbox", event.clientY);
      this.apply_drag(event.clientY);
    }
  }

  async ondrag_mail(ev) {
    ev.dataTransfer.setData("text", ev.target.uid);
  }

  async ondrop_mailbox(ev) {
    stop_event(ev);
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
