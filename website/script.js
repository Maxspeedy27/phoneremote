(() => {
  'use strict';
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- Hero demo: the phone's Next/Back change the laptop's slide ---------- */
  const slides = [...document.querySelectorAll('#deck .slide')];
  const num = document.getElementById('slide-num');
  const prevBtn = document.getElementById('demo-prev');
  const nextBtn = document.getElementById('demo-next');
  const clock = document.getElementById('p-clock');
  let current = 0;
  let started = null;

  function show(i) {
    const n = slides.length;
    const target = ((i % n) + n) % n;
    slides.forEach((s, k) => {
      s.classList.toggle('is-on', k === target);
      s.classList.toggle('is-prev', k < target);
    });
    current = target;
    num.textContent = `${target + 1} / ${n}`;
    num.setAttribute('aria-label', `Slide ${target + 1} of ${n}: ${slides[target].dataset.title}`);
  }

  function press(btn, step) {
    nextBtn.classList.remove('nudge');
    btn.classList.add('pressed');
    setTimeout(() => btn.classList.remove('pressed'), 140);
    if (navigator.vibrate) { try { navigator.vibrate(8); } catch (_) {} }
    show(current + step);
    startClock();
  }

  function startClock() {
    if (started) return;
    started = Date.now();
    const tick = () => {
      const s = Math.floor((Date.now() - started) / 1000);
      clock.textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
    };
    tick();
    setInterval(tick, 1000);
  }

  if (slides.length && prevBtn && nextBtn) {
    nextBtn.addEventListener('click', () => press(nextBtn, 1));
    prevBtn.addEventListener('click', () => press(prevBtn, -1));

    // Swipe on the phone screen, like the real remote.
    const screen = nextBtn.closest('.phone-screen');
    let x0 = null;
    screen.addEventListener('pointerdown', e => { x0 = e.clientX; });
    screen.addEventListener('pointerup', e => {
      if (x0 === null) return;
      const dx = e.clientX - x0;
      x0 = null;
      if (Math.abs(dx) > 40 && !e.target.closest('button')) press(dx < 0 ? nextBtn : prevBtn, dx < 0 ? 1 : -1);
    });

    if (!reduceMotion) nextBtn.classList.add('nudge');
    show(0);
  }

  /* ---------- Detect the visitor's OS for the download buttons ---------- */
  const ua = navigator.userAgent;
  const platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || '';
  const isMobile = /Android|iPhone|iPad|iPod/i.test(ua) || (navigator.userAgentData && navigator.userAgentData.mobile)
    || (/Mac/.test(platform) && navigator.maxTouchPoints > 1);
  let os = null;
  if (!isMobile) {
    if (/Win/i.test(platform) || /Windows/.test(ua)) os = 'windows';
    else if (/Mac/i.test(platform) || /Mac OS X/.test(ua)) os = 'mac';
    else if (/Linux|X11/i.test(platform) || /Linux|X11/.test(ua)) os = 'linux';
  }
  const names = { windows: 'Windows', mac: 'macOS', linux: 'Linux' };
  if (os) {
    const card = document.querySelector(`.dl[data-os="${os}"]`);
    if (card) {
      card.classList.add('mine');
      card.parentElement.prepend(card);
    }
    document.querySelectorAll('[data-os-label]').forEach(el => { el.textContent = `Download for ${names[os]}`; });
  } else if (isMobile) {
    const note = document.querySelector('.on-phone-note');
    if (note) note.hidden = false;
  }

  /* ---------- Header border on scroll + active nav link ---------- */
  const header = document.querySelector('.site-header');
  const onScroll = () => header.classList.toggle('scrolled', window.scrollY > 8);
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });

  const links = [...document.querySelectorAll('.site-nav a')];
  const targets = links.map(a => document.querySelector(a.getAttribute('href'))).filter(Boolean);
  if ('IntersectionObserver' in window && targets.length) {
    const navIO = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (!e.isIntersecting) return;
        links.forEach(a => {
          const on = a.getAttribute('href') === `#${e.target.id}`;
          a.classList.toggle('active', on);
          if (on) a.setAttribute('aria-current', 'location'); else a.removeAttribute('aria-current');
        });
      });
    }, { rootMargin: '-45% 0px -50% 0px' });
    targets.forEach(t => navIO.observe(t));
  }

  /* ---------- Scroll reveal, staggered within each group ---------- */
  const reveals = [...document.querySelectorAll('.reveal')];
  if (reduceMotion || !('IntersectionObserver' in window)) {
    reveals.forEach(el => el.classList.add('in'));
  } else {
    const groups = new Map();
    reveals.forEach(el => {
      const g = el.parentElement;
      const i = groups.get(g) || 0;
      groups.set(g, i + 1);
      el.style.setProperty('--d', `${Math.min(i, 6) * 0.05}s`);
    });
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    reveals.forEach(el => io.observe(el));
  }

  const year = document.getElementById('year');
  if (year) year.textContent = new Date().getFullYear();
})();
