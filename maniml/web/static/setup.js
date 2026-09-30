// The first launch of ManimLive.app (docs/claerbout_experiment.md): two ways to run Python, chosen
// here, installed here. The shell does the installing and reports each
// step as `setup` events; this page only asks and shows. A plain script,
// so it speaks the Claerbout protocol itself rather than through
// src/shell.ts.
(function () {
  var shell = window.claerbout;
  var status = document.getElementById('status');
  var buttons = Array.prototype.slice.call(document.querySelectorAll('button[data-python]'));
  var busy = false;

  function say(text, state) {
    status.textContent = text;
    status.className = state || '';
  }

  function choose(python) {
    if (busy || !shell) return;
    busy = true;
    buttons.forEach(function (button) {
      button.disabled = true;
      button.classList.toggle('chosen', button.dataset.python === python);
    });
    say(python === 'uv' ? 'Getting ready…' : 'Opening…', 'working');
    shell.request({ type: 'choose', python: python });
  }

  var report = {
    progress: function (text) {
      say(text, 'working');
    },
    failed: function (text) {
      busy = false;
      buttons.forEach(function (button) {
        button.disabled = false;
        button.classList.remove('chosen');
      });
      say(text + '\nChoose again to retry.', 'failed');
    },
  };
  if (shell) {
    shell.on('setup', function (detail) {
      var show = report[detail && detail.kind];
      if (show) show(String(detail.text));
    });
  }

  buttons.forEach(function (button) {
    button.addEventListener('click', function () {
      choose(button.dataset.python);
    });
  });

  if (!shell) {
    buttons.forEach(function (button) {
      button.disabled = true;
    });
    say('This page is part of ManimLive.app.');
    return;
  }
  var wanted = new URLSearchParams(window.location.search).get('choose');
  if (wanted === 'uv' || wanted === 'browser') choose(wanted);
})();
