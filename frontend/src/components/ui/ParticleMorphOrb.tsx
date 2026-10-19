'use client';

import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

export interface ParticleMorphOrbProps {
  className?: string;
  size?: number;
  speed?: number;
  pointCount?: number;
}

const vertexShader = `
uniform float uTime;
varying float vFresnel;
varying float vAlpha;

// 3D Simplex noise
vec4 permute(vec4 x){return mod(((x*34.0)+1.0)*x, 289.0);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159 - 0.85373472095314 * r;}
float snoise(vec3 v){
  const vec2  C = vec2(1.0/6.0, 1.0/3.0);
  const vec4  D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i  = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + 1.0 * C.xxx;
  vec3 x2 = x0 - i2 + 2.0 * C.xxx;
  vec3 x3 = x0 - 1.0 + 3.0 * C.xxx;
  i = mod(i, 289.0);
  vec4 p = permute(permute(permute(
             i.z + vec4(0.0, i1.z, i2.z, 1.0))
           + i.y + vec4(0.0, i1.y, i2.y, 1.0))
           + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  float n_ = 0.142857142857;
  vec3  ns = n_ * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z *ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ *ns.x + ns.yyyy;
  vec4 y = y_ *ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0)*2.0 + 1.0;
  vec4 s1 = floor(b1)*2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww;
  vec3 p0 = vec3(a0.xy,h.x);
  vec3 p1 = vec3(a0.zw,h.y);
  vec3 p2 = vec3(a1.xy,h.z);
  vec3 p3 = vec3(a1.zw,h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2, p2), dot(p3,p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
  m = m * m;
  return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
}

void main() {
  vec3 norm = normalize(position);
  
  float t = uTime * 0.95;
  
  // Breathing modulation: pulses between gentle sphere and deep organic lobes
  float breath = 0.5 + 0.5 * sin(t * 0.7);
  
  // Spherical coordinates
  float angle = atan(norm.y, norm.x);
  float elevation = acos(clamp(norm.z, -1.0, 1.0));
  
  // 4-lobe harmonic wave matching the video's undulating petal folds
  float lobeWave = sin(4.0 * angle + t * 0.85) * sin(3.0 * elevation + t * 0.45) * 0.24;
  
  // Multi-frequency simplex noise for fluid ripples
  float noise1 = snoise(norm * 1.8 + vec3(0.0, t * 0.45, t * 0.25)) * 0.18;
  float noise2 = snoise(norm * 3.5 - vec3(t * 0.35, -t * 0.25, t * 0.15)) * 0.08;
  
  float disp = (lobeWave + noise1 + noise2) * (0.65 + 0.35 * breath);
  vec3 displaced = position + norm * disp;
  
  vec4 mvPosition = modelViewMatrix * vec4(displaced, 1.0);
  gl_Position = projectionMatrix * mvPosition;
  
  // Pinpoint star dots - delicate and crisp
  gl_PointSize = 1.35;
  
  // Edge grazing accumulation for bright glowing rim folds
  vec3 viewDir = normalize(-mvPosition.xyz);
  vec3 worldNormal = normalize(normalMatrix * norm);
  float edge = 1.0 - abs(dot(worldNormal, viewDir));
  vFresnel = pow(edge, 2.2);
  
  // Depth-based transparency: front dots are clear, back dots are softer
  vAlpha = smoothstep(-1.2, 1.0, norm.z) * 0.5 + 0.5;
}
`;

const fragmentShader = `
varying float vFresnel;
varying float vAlpha;

void main() {
  vec2 coord = gl_PointCoord - vec2(0.5);
  float dist = length(coord);
  if (dist > 0.5) discard;
  
  // Soft circular dot
  float shape = smoothstep(0.5, 0.1, dist);
  
  // Rim folds glow intensely white while interior dots are delicate translucent stars
  float brightness = 0.15 + vFresnel * 0.85;
  float alpha = shape * brightness * vAlpha * 0.75;
  
  gl_FragColor = vec4(vec3(0.96, 0.98, 1.0), alpha);
}
`;

export default function ParticleMorphOrb({
  className = '',
  size = 56,
  speed = 1.0,
  pointCount = 1800,
}: ParticleMorphOrbProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hasWebGL, setHasWebGL] = useState(true);
  const isDraggingRef = useRef(false);
  const prevPointerRef = useRef({ x: 0, y: 0 });
  const rotationVelocityRef = useRef({ x: 0.002, y: 0.007 });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const width = container.clientWidth || size;
    const height = container.clientHeight || size;

    let renderer: THREE.WebGLRenderer | null = null;
    let scene: THREE.Scene | null = null;
    let camera: THREE.PerspectiveCamera | null = null;
    let group: THREE.Group | null = null;
    let points: THREE.Points | null = null;
    let geometry: THREE.BufferGeometry | null = null;
    let baseGeom: THREE.SphereGeometry | null = null;
    let material: THREE.ShaderMaterial | null = null;
    let animationFrameId: number = 0;
    let resizeObserver: ResizeObserver | null = null;

    try {
      scene = new THREE.Scene();
      camera = new THREE.PerspectiveCamera(38, width / height, 0.1, 100);
      camera.position.set(0, 0, 4.3);

      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(typeof window !== 'undefined' ? window.devicePixelRatio : 1, 2.0));
      container.appendChild(renderer.domElement);

      group = new THREE.Group();
      // Tilt to show the pole spiral angle seen in the video
      group.rotation.x = 0.52;
      group.rotation.z = -0.28;
      scene.add(group);

      // Concentric latitude rings matching video
      baseGeom = new THREE.SphereGeometry(1.18, 54, 36);
      geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', baseGeom.getAttribute('position'));

      material = new THREE.ShaderMaterial({
        vertexShader,
        fragmentShader,
        uniforms: {
          uTime: { value: 0 },
        },
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });

      points = new THREE.Points(geometry, material);
      group.add(points);
    } catch (e) {
      if (typeof process !== 'undefined' && process.env?.NODE_ENV !== 'test') {
        console.warn('WebGL not available for ParticleMorphOrb, using CSS fallback:', e);
      }
      setHasWebGL(false);
      return;
    }

    const clock = new THREE.Clock();

    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);
      const elapsedTime = clock.getElapsedTime() * speed;

      if (material && material.uniforms?.uTime) {
        material.uniforms.uTime.value = elapsedTime * 1.25;
      }

      if (group && !isDraggingRef.current) {
        group.rotation.y += rotationVelocityRef.current.y;
        group.rotation.x += rotationVelocityRef.current.x;
        rotationVelocityRef.current.y = THREE.MathUtils.lerp(rotationVelocityRef.current.y, 0.005, 0.04);
        rotationVelocityRef.current.x = THREE.MathUtils.lerp(rotationVelocityRef.current.x, 0.0025, 0.04);
      }

      if (renderer && scene && camera) {
        renderer.render(scene, camera);
      }
    };

    animate();

    const handleResize = () => {
      if (!container || !camera || !renderer) return;
      const w = container.clientWidth || size;
      const h = container.clientHeight || size;
      if (w === 0 || h === 0) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };

    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(handleResize);
      resizeObserver.observe(container);
    }

    const onPointerDown = (e: PointerEvent) => {
      isDraggingRef.current = true;
      prevPointerRef.current = { x: e.clientX, y: e.clientY };
    };

    const onPointerMove = (e: PointerEvent) => {
      if (!isDraggingRef.current || !group) return;
      const dx = e.clientX - prevPointerRef.current.x;
      const dy = e.clientY - prevPointerRef.current.y;
      prevPointerRef.current = { x: e.clientX, y: e.clientY };

      group.rotation.y += dx * 0.01;
      group.rotation.x += dy * 0.01;
      rotationVelocityRef.current = { x: dy * 0.003, y: dx * 0.003 };
    };

    const onPointerUp = () => {
      isDraggingRef.current = false;
    };

    container.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);

    return () => {
      cancelAnimationFrame(animationFrameId);
      if (resizeObserver) resizeObserver.disconnect();
      container.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      if (renderer) {
        if (renderer.domElement.parentNode === container) {
          container.removeChild(renderer.domElement);
        }
        renderer.dispose();
      }
      if (geometry) geometry.dispose();
      if (baseGeom) baseGeom.dispose();
      if (material) material.dispose();
    };
  }, [size, speed, pointCount]);

  if (!hasWebGL) {
    return (
      <div
        style={{ width: size, height: size }}
        className={`relative flex items-center justify-center ${className}`}
      >
        <div
          style={{
            width: Math.max(14, size * 0.65),
            height: Math.max(14, size * 0.65),
            borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(147,197,253,0.95) 0%, rgba(59,130,246,0.5) 50%, rgba(14,165,233,0.1) 80%, transparent 100%)',
            boxShadow: '0 0 16px rgba(56,189,248,0.7)',
            animation: 'pulse 1.8s infinite ease-in-out',
          }}
        />
      </div>
    );
  }

  return (
    <div
      style={{ width: size, height: size }}
      className={`relative flex items-center justify-center cursor-grab active:cursor-grabbing select-none ${className}`}
    >
      <div ref={containerRef} className="w-full h-full flex items-center justify-center pointer-events-none" />
    </div>
  );
}

// ─── RewampUI Capsule Thinking / Evaluating Pill ───────────────────
const DEFAULT_THINKING_MESSAGES = [
  'evaluating policy invariants...',
  'verifying budget ceilings...',
  'querying catalogue for verified SKUs...',
  'checking zero-drift constraints...',
  'compiling cryptographic proposal...',
  'deep thinking...',
];

export interface AiThinkingOrbProps {
  text?: string;
  subtext?: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
  cycleMessages?: string[];
}

export function AiThinkingOrb({
  text,
  subtext,
  size = 'md',
  className = '',
  cycleMessages = DEFAULT_THINKING_MESSAGES,
}: AiThinkingOrbProps) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (text) return;
    const interval = setInterval(() => {
      setIndex((prev) => (prev + 1) % cycleMessages.length);
    }, 2400);
    return () => clearInterval(interval);
  }, [text, cycleMessages.length]);

  const orbSize = size === 'sm' ? 24 : size === 'lg' ? 44 : 34;
  const displayText = text || cycleMessages[index];

  return (
    <div
      className={`inline-flex items-center gap-3 px-4 py-2 rounded-full text-white select-none ${className}`}
      style={{
        background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.94) 0%, rgba(10, 15, 30, 0.96) 100%)',
        backdropFilter: 'blur(12px)',
        border: '1px solid rgba(255, 255, 255, 0.12)',
        boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.45), 0 0 15px rgba(0, 112, 186, 0.25)',
      }}
    >
      <div style={{ flexShrink: 0, width: orbSize, height: orbSize }} className="flex items-center justify-center">
        <ParticleMorphOrb size={orbSize} speed={1.1} />
      </div>
      <div className="flex flex-col text-left">
        <span
          style={{
            fontSize: size === 'sm' ? '0.74rem' : size === 'lg' ? '0.9rem' : '0.82rem',
            fontWeight: 500,
            letterSpacing: '0.02em',
            color: '#f8fafc',
            fontFamily: 'system-ui, -apple-system, sans-serif',
          }}
        >
          {displayText}
        </span>
        {subtext && (
          <span style={{ fontSize: '0.66rem', color: '#94a3b8', marginTop: '-1px' }}>
            {subtext}
          </span>
        )}
      </div>
    </div>
  );
}

// ─── Rich AI Invariant Engine Evaluation Card ───────────────────────
export interface AiThinkingCardProps {
  currentStage?: number; // 1 to 4
  stageTitle?: string;
  className?: string;
}

export function AiThinkingCard({
  currentStage = 2,
  stageTitle = 'Evaluating Purchase Invariants',
  className = '',
}: AiThinkingCardProps) {
  const [msgIdx, setMsgIdx] = useState(0);

  useEffect(() => {
    const t = setInterval(() => {
      setMsgIdx((prev) => (prev + 1) % DEFAULT_THINKING_MESSAGES.length);
    }, 2200);
    return () => clearInterval(t);
  }, []);

  const stages = [
    { num: 1, label: 'Natural Language Intent' },
    { num: 2, label: 'Policy Invariant Guard' },
    { num: 3, label: 'Catalogue SKU Verification' },
    { num: 4, label: 'SHA-256 Fingerprint' },
  ];

  return (
    <div
      className={`clean-card ${className}`}
      style={{
        padding: '24px 20px',
        textAlign: 'center',
        background: 'linear-gradient(180deg, #0b1120 0%, #060913 100%)',
        color: '#f8fafc',
        borderRadius: '12px',
        border: '1px solid rgba(56, 189, 248, 0.2)',
        boxShadow: '0 20px 40px -15px rgba(0, 0, 0, 0.6), 0 0 25px rgba(0, 112, 186, 0.18)',
        minHeight: '380px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Background radial glow */}
      <div
        style={{
          position: 'absolute',
          top: '35%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: '260px',
          height: '260px',
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(0, 112, 186, 0.18) 0%, rgba(56, 189, 248, 0.08) 50%, transparent 75%)',
          pointerEvents: 'none',
        }}
      />

      {/* Top Header Badge */}
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          padding: '3px 10px',
          borderRadius: '9999px',
          background: 'rgba(255, 255, 255, 0.08)',
          border: '1px solid rgba(255, 255, 255, 0.12)',
          fontSize: '0.68rem',
          letterSpacing: '0.05em',
          fontWeight: 600,
          color: '#38bdf8',
          marginBottom: '12px',
          zIndex: 1,
        }}
      >
        <span
          style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: '#38bdf8',
            boxShadow: '0 0 8px #38bdf8',
            animation: 'pulse 1.5s infinite',
          }}
        />
        AI INVARIANT ENGINE ACTIVE
      </div>

      {/* Central 3D Interactive Particle Morph Orb */}
      <div style={{ position: 'relative', width: 130, height: 130, margin: '4px auto 14px', zIndex: 1 }}>
        <ParticleMorphOrb size={130} speed={1.3} />
      </div>

      {/* Dynamic Animated Status */}
      <h3
        style={{
          fontSize: '1rem',
          fontWeight: 700,
          color: '#ffffff',
          marginBottom: '4px',
          letterSpacing: '-0.01em',
          zIndex: 1,
        }}
      >
        {stageTitle}
      </h3>
      <p
        style={{
          fontSize: '0.78rem',
          color: '#94a3b8',
          maxWidth: '320px',
          margin: '0 auto 16px',
          minHeight: '1.4em',
          zIndex: 1,
        }}
      >
        {DEFAULT_THINKING_MESSAGES[msgIdx]}
      </p>

      {/* 4 Pipeline Step Dots */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: '8px',
          width: '100%',
          maxWidth: '380px',
          zIndex: 1,
        }}
      >
        {stages.map((st) => {
          const isActive = st.num === currentStage;
          const isDone = st.num < currentStage;
          return (
            <div
              key={st.num}
              style={{
                background: isActive
                  ? 'rgba(0, 112, 186, 0.25)'
                  : isDone
                  ? 'rgba(16, 185, 129, 0.15)'
                  : 'rgba(255, 255, 255, 0.04)',
                border: `1px solid ${
                  isActive
                    ? '#0070ba'
                    : isDone
                    ? 'rgba(16, 185, 129, 0.4)'
                    : 'rgba(255, 255, 255, 0.08)'
                }`,
                borderRadius: '6px',
                padding: '6px 4px',
                fontSize: '0.64rem',
                color: isActive ? '#38bdf8' : isDone ? '#34d399' : '#64748b',
                transition: 'all 0.3s ease',
              }}
            >
              <div style={{ fontWeight: 700, marginBottom: '2px' }}>
                {isDone ? '✓' : `0${st.num}`}
              </div>
              <div style={{ lineHeight: '1.2' }}>{st.label}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
