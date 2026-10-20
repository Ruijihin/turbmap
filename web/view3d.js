// 揺れやすさの3D表示(three.js のボリュームレンダリング)。
// index.html から import('./view3d.js') で読み込まれる。
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';

const VERT = `
  varying vec3 vOrigin; varying vec3 vDir;
  void main(){
    vec4 mv = modelViewMatrix * vec4(position,1.0);
    vOrigin = (inverse(modelMatrix) * vec4(cameraPosition,1.0)).xyz;
    vDir = position - vOrigin;
    gl_Position = projectionMatrix * mv;
  }`;

const FRAG = `
  precision highp float; precision highp sampler3D;
  varying vec3 vOrigin; varying vec3 vDir;
  uniform sampler3D uVol;
  uniform float uThr, uDens, uYLo, uYHi, uMode;
  uniform vec3 uC0, uC1, uC2, uC3, uColorEl;
  vec2 hitBox(vec3 o, vec3 d){
    vec3 inv = 1.0/d;
    vec3 a = (vec3(-0.5)-o)*inv, b = (vec3(0.5)-o)*inv;
    vec3 tmin = min(a,b), tmax = max(a,b);
    return vec2(max(max(tmin.x,tmin.y),tmin.z), min(min(tmax.x,tmax.y),tmax.z));
  }
  vec3 ramp(float s){
    if(uMode > 0.5) return uColorEl;
    if(s < 0.8) return mix(uC0,uC1,clamp((s-0.5)/0.3,0.0,1.0));
    if(s < 1.2) return mix(uC1,uC2,(s-0.8)/0.4);
    return mix(uC2,uC3,clamp((s-1.2)/0.4,0.0,1.0));
  }
  void main(){
    vec3 rd = normalize(vDir);
    vec2 b = hitBox(vOrigin, rd);
    if(b.x > b.y) discard;
    b.x = max(b.x, 0.0);
    vec3 p = vOrigin + b.x*rd;
    float len = b.y - b.x;
    const int STEPS = 220;
    float dt = len / float(STEPS);
    vec3 col = vec3(0.0); float acc = 0.0;
    for(int i=0;i<STEPS;i++){
      if(p.y >= uYLo && p.y <= uYHi){
        float s = texture(uVol, vec3(p.x+0.5, p.z+0.5, p.y+0.5)).r * 2.55;
        float a = smoothstep(uThr-0.04, uThr+0.04, s) * (0.3 + 0.7*clamp((s-uThr)/0.9,0.0,1.0));
        if(a > 0.001){
          float aStep = 1.0 - exp(-a * uDens * dt * 9.0);
          col += (1.0-acc) * aStep * ramp(s);
          acc += (1.0-acc) * aStep;
          if(acc > 0.97) break;
        }
      }
      p += rd * dt;
    }
    if(acc < 0.003) discard;
    gl_FragColor = vec4(col/acc, acc);
  }`;

function textSprite(text, color, size = 64) {
  const c = document.createElement('canvas'); c.width = 256; c.height = 64;
  const x = c.getContext('2d'); x.font = `bold ${size * 0.62}px sans-serif`; x.textBaseline = 'middle';
  x.fillStyle = color; x.fillText(text, 4, 32);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  const m = new THREE.SpriteMaterial({ map: t, depthTest: false, transparent: true });
  const s = new THREE.Sprite(m); s.scale.set(1.6, 0.4, 1); s.center.set(0, 0.5); s.renderOrder = 10;
  return s;
}

const hexv = h => new THREE.Color(h);

export function create(container) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  container.appendChild(renderer.domElement);
  renderer.domElement.style.cssText = 'display:block;width:100%;height:100%;touch-action:none';
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 200);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = false; controls.maxPolarAngle = Math.PI * 0.62; controls.minDistance = 6; controls.maxDistance = 90;
  let want = false;
  const render = () => { want = false; renderer.render(scene, camera); };
  const request = () => { if (!want) { want = true; requestAnimationFrame(render); } };
  controls.addEventListener('change', request);

  const W = 22.4, D = 23.6;               // 水平の大きさ(緯度1度=1)
  let H = 3.2, st = null, dims = null;
  const group = new THREE.Group(); scene.add(group);
  const mat = new THREE.ShaderMaterial({
    vertexShader: VERT, fragmentShader: FRAG, side: THREE.BackSide, transparent: true, depthWrite: false,
    uniforms: {
      uVol: { value: null }, uThr: { value: 0.8 }, uDens: { value: 1.0 }, uYLo: { value: -0.5 }, uYHi: { value: 0.5 }, uMode: { value: 0 },
      uC0: { value: hexv('#ffe08a') }, uC1: { value: hexv('#ffa94d') }, uC2: { value: hexv('#e8590c') }, uC3: { value: hexv('#9b1111') },
      uColorEl: { value: hexv('#7b2cbf') },
    },
  });
  const box = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), mat); box.renderOrder = 5;
  group.add(box);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ color: 0xffffff }));
  ground.rotation.x = -Math.PI / 2; ground.renderOrder = 0; group.add(ground);
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)), new THREE.LineBasicMaterial({ color: 0x8a94a3 }));
  group.add(edges);
  const labels = new THREE.Group(); scene.add(labels);

  function layout() {
    box.scale.set(W, H, D); edges.scale.set(W, H, D);
    box.position.y = H / 2; edges.position.y = H / 2;
    ground.scale.set(W, D, 1); ground.position.y = -0.002;
    // 高度の目盛り(手前左の角)
    labels.clear();
    if (!dims) return;
    const { flMin, flMax } = dims, fg = st.label;
    for (let fl = Math.ceil(flMin / 50) * 50; fl <= flMax; fl += 50) {
      const y = (fl - flMin) / (flMax - flMin) * H;
      const s = textSprite('FL' + fl, fg); s.position.set(-W / 2 - 0.55, y, D / 2 + 0.1); labels.add(s);
      const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-W / 2, y, D / 2), new THREE.Vector3(-W / 2 - 0.5, y, D / 2)]);
      labels.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: new THREE.Color(fg) })));
    }
    const n = textSprite('北', fg); n.position.set(0, 0.02, -D / 2 - 0.3); n.scale.set(0.8, 0.4, 1); labels.add(n);
  }

  function resize() {
    const r = container.getBoundingClientRect();
    renderer.setSize(r.width, r.height, false);
    camera.aspect = r.width / Math.max(r.height, 1); camera.updateProjectionMatrix(); request();
  }
  new ResizeObserver(resize).observe(container);

  const api = {
    /** v: Float32Array(nx*ny*nz)  インデックス = x + y*nx + z*nx*ny(y:北→南, z:低→高) */
    setVolume(v, nx, ny, nz, flMin, flMax) {
      const u8 = new Uint8Array(v.length);
      // v は指数(1.0=並)。テクスチャには v*100 を0〜255で入れ、シェーダーで 255分の1 して 2.55 を掛けて戻す
      for (let i = 0; i < v.length; i++) u8[i] = Math.max(0, Math.min(255, Math.round(v[i] * 100)));
      if (mat.uniforms.uVol.value) mat.uniforms.uVol.value.dispose();
      const t = new THREE.Data3DTexture(u8, nx, ny, nz);
      t.format = THREE.RedFormat; t.type = THREE.UnsignedByteType; t.minFilter = THREE.LinearFilter; t.magFilter = THREE.LinearFilter;
      t.wrapS = t.wrapT = t.wrapR = THREE.ClampToEdgeWrapping; t.unpackAlignment = 1; t.needsUpdate = true;
      mat.uniforms.uVol.value = t; dims = { flMin, flMax }; layout(); request();
    },
    setGround(canvas) {
      const t = new THREE.CanvasTexture(canvas); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
      if (ground.material.map) ground.material.map.dispose();
      ground.material.map = t; ground.material.color.set(0xffffff); ground.material.needsUpdate = true; request();
    },
    setStyle(s) { st = s; edges.material.color.set(s.edge); renderer.setClearColor(0x000000, 0); layout(); request(); },
    setOptions(o) {
      if (o.thr != null) mat.uniforms.uThr.value = o.thr;
      if (o.dens != null) mat.uniforms.uDens.value = o.dens;
      if (o.mode != null) mat.uniforms.uMode.value = o.mode;
      if (o.color) mat.uniforms.uColorEl.value = hexv(o.color);
      if (o.ramp) ['uC0', 'uC1', 'uC2', 'uC3'].forEach((k, i) => mat.uniforms[k].value = hexv(o.ramp[i]));
      if (o.exag != null) { H = (dims ? (dims.flMax - dims.flMin) : 290) * 30.48 / 1000 / 111.2 * o.exag; layout(); }
      if (o.flLo != null && dims) {
        const f = (x) => (x - dims.flMin) / (dims.flMax - dims.flMin) - 0.5;
        mat.uniforms.uYLo.value = f(o.flLo); mat.uniforms.uYHi.value = f(o.flHi);
      }
      request();
    },
    show() { container.hidden = false; resize(); if (!api._init) { api.resetView(); api._init = true; } request(); },
    hide() { container.hidden = true; },
    resetView() { camera.position.set(-6, 15, 31); controls.target.set(0, 0.8, 1.5); controls.update(); request(); },
    view(name) {
      const t = controls.target;
      if (name === 'top') camera.position.set(t.x, 42, t.z + 0.01);
      else if (name === 'east') camera.position.set(36, 7, 0);
      else if (name === 'south') camera.position.set(0, 7, 36);
      else camera.position.set(-6, 15, 31);
      controls.update(); request();
    },
    request,
  };
  return api;
}
