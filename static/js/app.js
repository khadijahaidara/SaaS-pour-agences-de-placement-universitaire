/* NEURALIS Mobility — interactions sans dépendance externe. */
(function () {
  "use strict";

  /* ------------------------------------------------------------------ */
  /* Listes déroulantes avec recherche : améliore les <select class=input> */
  /* ------------------------------------------------------------------ */
  var comboSeq = 0;

  function normalize(s) {
    return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function enhanceSelect(select) {
    if (select.dataset.comboReady || select.multiple || select.dataset.native !== undefined) return;
    select.dataset.comboReady = "1";
    var id = "combo-" + (++comboSeq);
    var wrap = document.createElement("div");
    wrap.className = "combo";
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "combo-btn";
    btn.setAttribute("aria-haspopup", "listbox");
    btn.setAttribute("aria-expanded", "false");
    if (select.id) {
      var lbl = document.querySelector('label[for="' + select.id + '"]');
      if (lbl) { lbl.htmlFor = id + "-btn"; btn.setAttribute("aria-label", lbl.textContent.trim()); }
    }
    btn.id = id + "-btn";
    btn.innerHTML = '<span class="val"></span><svg class="ic sm"><use href="#i-chevron-down"></use></svg>';
    wrap.appendChild(btn);

    var pop = document.createElement("div");
    pop.className = "combo-pop";
    var options = Array.prototype.slice.call(select.options);
    var searchable = options.length > 6;
    var search = null;
    if (searchable) {
      search = document.createElement("input");
      search.type = "search";
      search.className = "combo-search";
      search.placeholder = "Rechercher…";
      search.setAttribute("aria-label", "Rechercher dans la liste");
      pop.appendChild(search);
    }
    var list = document.createElement("ul");
    list.className = "combo-list";
    list.setAttribute("role", "listbox");
    list.id = id + "-list";
    pop.appendChild(list);
    wrap.appendChild(pop);

    var activeIndex = -1;
    var visible = [];

    function label() {
      var opt = select.options[select.selectedIndex];
      var span = btn.querySelector(".val");
      var text = opt ? opt.text : "";
      span.textContent = text || "—";
      span.classList.toggle("ph", !opt || opt.value === "");
    }

    function render(filter) {
      list.innerHTML = "";
      visible = [];
      var f = normalize(filter);
      options.forEach(function (opt, i) {
        if (f && normalize(opt.text).indexOf(f) === -1) return;
        var li = document.createElement("li");
        li.setAttribute("role", "option");
        li.textContent = opt.text;
        li.dataset.index = i;
        li.setAttribute("aria-selected", i === select.selectedIndex ? "true" : "false");
        li.addEventListener("mousedown", function (e) { e.preventDefault(); choose(i); });
        list.appendChild(li);
        visible.push(li);
      });
      if (!visible.length) {
        var empty = document.createElement("li");
        empty.className = "empty";
        empty.textContent = "Aucun résultat";
        list.appendChild(empty);
      }
      activeIndex = visible.findIndex(function (li) { return li.getAttribute("aria-selected") === "true"; });
      highlight();
    }

    function highlight() {
      visible.forEach(function (li, i) { li.classList.toggle("active", i === activeIndex); });
      if (visible[activeIndex]) visible[activeIndex].scrollIntoView({ block: "nearest" });
    }

    function open() {
      closeAllCombos(wrap);
      render("");
      var rect = wrap.getBoundingClientRect();
      wrap.classList.toggle("up", window.innerHeight - rect.bottom < 300 && rect.top > 320);
      wrap.classList.add("open");
      btn.setAttribute("aria-expanded", "true");
      if (search) { search.value = ""; search.focus(); }
    }

    function close(focusBtn) {
      wrap.classList.remove("open");
      btn.setAttribute("aria-expanded", "false");
      if (focusBtn) btn.focus();
    }

    function choose(i) {
      select.selectedIndex = i;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      label();
      close(true);
    }

    function onKey(e) {
      if (e.key === "ArrowDown") { e.preventDefault(); activeIndex = Math.min(activeIndex + 1, visible.length - 1); highlight(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); activeIndex = Math.max(activeIndex - 1, 0); highlight(); }
      else if (e.key === "Enter") { e.preventDefault(); if (visible[activeIndex]) choose(+visible[activeIndex].dataset.index); }
      else if (e.key === "Escape") { e.preventDefault(); close(true); }
      else if (e.key === "Tab") { close(false); }
    }

    btn.addEventListener("click", function () { wrap.classList.contains("open") ? close(true) : open(); });
    btn.addEventListener("keydown", function (e) {
      if (!wrap.classList.contains("open") && (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ")) { e.preventDefault(); open(); }
      else if (wrap.classList.contains("open")) onKey(e);
    });
    if (search) {
      search.addEventListener("input", function () { render(search.value); activeIndex = visible.length ? 0 : -1; highlight(); });
      search.addEventListener("keydown", onKey);
    }
    select.addEventListener("change", label);
    label();
  }

  function closeAllCombos(except) {
    document.querySelectorAll(".combo.open").forEach(function (c) {
      if (c !== except) { c.classList.remove("open"); c.querySelector(".combo-btn").setAttribute("aria-expanded", "false"); }
    });
  }

  document.addEventListener("click", function (e) {
    if (!e.target.closest(".combo")) closeAllCombos(null);
  });

  /* ------------------------------------------------------------------ */
  /* Menus déroulants <details class="dd">                                */
  /* ------------------------------------------------------------------ */
  document.addEventListener("click", function (e) {
    document.querySelectorAll("details.dd[open]").forEach(function (d) {
      if (!d.contains(e.target)) d.removeAttribute("open");
    });
  });
  document.addEventListener("toggle", function (e) {
    var d = e.target;
    if (d.matches && d.matches("details.dd") && d.open) {
      document.querySelectorAll("details.dd[open]").forEach(function (o) { if (o !== d) o.removeAttribute("open"); });
    }
  }, true);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") document.querySelectorAll("details.dd[open]").forEach(function (d) {
      d.removeAttribute("open"); var s = d.querySelector("summary"); if (s) s.focus();
    });
  });

  /* ------------------------------------------------------------------ */
  /* Fenêtres modales <dialog>                                           */
  /* ------------------------------------------------------------------ */
  document.addEventListener("click", function (e) {
    var opener = e.target.closest("[data-open-modal]");
    if (opener) {
      var dlg = document.getElementById(opener.dataset.openModal);
      if (dlg && dlg.showModal) {
        e.preventDefault();
        document.querySelectorAll("details.dd[open]").forEach(function (d) { d.removeAttribute("open"); });
        dlg.showModal();
        var first = dlg.querySelector("input:not([type=hidden]), textarea, .combo-btn, select");
        if (first) first.focus();
      }
      return;
    }
    if (e.target.closest("[data-close-modal]")) {
      var d = e.target.closest("dialog");
      if (d) d.close();
      return;
    }
    if (e.target.tagName === "DIALOG" && e.target.classList.contains("modal")) {
      var r = e.target.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) e.target.close();
    }
  });

  /* ------------------------------------------------------------------ */
  /* Notifications toast                                                 */
  /* ------------------------------------------------------------------ */
  function initToasts() {
    document.querySelectorAll(".toast").forEach(function (t) {
      var btn = t.querySelector("button");
      if (btn) btn.addEventListener("click", function () { t.remove(); });
      if (!t.classList.contains("error")) setTimeout(function () { t.style.opacity = "0"; t.style.transition = "opacity .3s"; setTimeout(function () { t.remove(); }, 320); }, 6000);
    });
  }

  /* ------------------------------------------------------------------ */
  /* Divers : barre latérale mobile, copie, fichiers, envoi automatique   */
  /* ------------------------------------------------------------------ */
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-sidebar-toggle]")) { document.body.classList.toggle("sidebar-open"); return; }
    if (document.body.classList.contains("sidebar-open") && !e.target.closest(".sidebar")) document.body.classList.remove("sidebar-open");
    var copy = e.target.closest("[data-copy]");
    if (copy) {
      var src = document.querySelector(copy.dataset.copy);
      if (src && navigator.clipboard) {
        navigator.clipboard.writeText(src.value || src.textContent).then(function () {
          var old = copy.innerHTML; copy.textContent = "Copié"; setTimeout(function () { copy.innerHTML = old; }, 1600);
        });
      }
    }
  });

  document.addEventListener("change", function (e) {
    var t = e.target;
    if (t.matches("[data-autosubmit]") && t.form) t.form.requestSubmit ? t.form.requestSubmit() : t.form.submit();
    if (t.matches(".dropzone input[type=file]")) {
      var zone = t.closest(".dropzone");
      var name = zone.querySelector(".fname");
      if (name) name.textContent = t.files.length ? t.files[0].name : name.dataset.empty;
    }
  });

  ["dragenter", "dragover"].forEach(function (ev) {
    document.addEventListener(ev, function (e) { var z = e.target.closest && e.target.closest(".dropzone"); if (z) { e.preventDefault(); z.classList.add("drag"); } });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    document.addEventListener(ev, function (e) {
      var z = e.target.closest && e.target.closest(".dropzone");
      if (!z) return;
      z.classList.remove("drag");
      if (ev === "drop") {
        e.preventDefault();
        var input = z.querySelector("input[type=file]");
        if (input && e.dataTransfer.files.length) { input.files = e.dataTransfer.files; input.dispatchEvent(new Event("change", { bubbles: true })); }
      }
    });
  });

  // Évite les doubles envois (connexion lente) : désactive le bouton après le premier clic.
  document.addEventListener("submit", function (e) {
    var btn = e.submitter;
    if (btn && !e.defaultPrevented) setTimeout(function () { btn.disabled = true; }, 0);
  });

  function init() {
    document.querySelectorAll("select.input").forEach(enhanceSelect);
    initToasts();
    document.querySelectorAll("dialog[data-autoopen]").forEach(function (d) { if (d.showModal) d.showModal(); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
