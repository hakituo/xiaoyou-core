import React, { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Float } from '@react-three/drei';
import * as THREE from 'three';
import { EMOTIONS } from '../utils/emotion';
import { EmotionType } from '../types';

interface SciFiCoreProps {
  colors?: [string, string, string, string];
  emotionColor?: string;
  isSpeaking: boolean;
  emotion?: EmotionType;
}

const CrystalPrism = ({ colors, isSpeaking }: { colors: string[], isSpeaking: boolean }) => {
  const meshRef = useRef<THREE.Mesh>(null);
  const outerRef = useRef<THREE.Mesh>(null);
  const coreRef = useRef<THREE.Mesh>(null);
  const edgeRef = useRef<THREE.LineSegments>(null);

  const speedRef = useRef(1.0);

  useFrame((state) => {
    const time = state.clock.getElapsedTime();
    const targetSpeed = isSpeaking ? 2.5 : 1.0;
    
    speedRef.current = THREE.MathUtils.lerp(speedRef.current, targetSpeed, 0.05);
    const speed = speedRef.current;

    if (meshRef.current) {
      meshRef.current.rotation.y = time * 0.4 * speed;
      meshRef.current.rotation.z = time * 0.2 * speed;
      const pulse = 1 + Math.sin(time * 1.5 * speed) * 0.05;
      meshRef.current.scale.set(pulse, pulse, pulse);
      
      if (edgeRef.current) {
        edgeRef.current.rotation.copy(meshRef.current.rotation);
        edgeRef.current.scale.copy(meshRef.current.scale);
      }
    }

    if (outerRef.current) {
      outerRef.current.rotation.y = -time * 0.1 * speed;
      outerRef.current.rotation.x = time * 0.08 * speed;
    }

    if (coreRef.current) {
      // 内部核心高频旋转并上下漂浮，模拟呼吸灯内部效果
      coreRef.current.rotation.x = -time * 1.2 * speed;
      coreRef.current.rotation.y = time * 0.8 * speed;
      const corePulse = 0.6 + Math.sin(time * 3 * speed) * 0.1;
      coreRef.current.scale.set(corePulse, corePulse, corePulse);
    }
  });

  return (
    <group>
      {/* 1. 内部发光核心 (The Core Object) - 增加物理感和光影对比 */}
      <mesh ref={coreRef}>
        <octahedronGeometry args={[0.7, 0]} />
        <meshStandardMaterial 
          color={colors[0]} 
          emissive={colors[0]}
          emissiveIntensity={1.5}
          metalness={0.8}
          roughness={0.2}
          flatShading={true} // 关键：开启平直着色，让棱角分明，体现立体感
        />
        <pointLight intensity={10} color={colors[0]} distance={4} />
      </mesh>

      {/* 2. 主棱镜外壳 (Semi-transparent Shell) */}
      <mesh ref={meshRef}>
        <octahedronGeometry args={[1.5, 0]} />
        <meshPhysicalMaterial
          color={colors[1]}
          transparent={true}
          opacity={0.3} // 降低一点不透明度，让内部核心更清晰
          roughness={0.05}
          metalness={0.1}
          transmission={0.7} // 增加透光感，模拟更纯净的晶体
          thickness={1.5} 
          envMapIntensity={1.5}
          clearcoat={1}
          clearcoatRoughness={0}
        />
      </mesh>

      {/* 3. 强化棱角线条 - 增加粗细感 */}
      <lineSegments ref={edgeRef}>
        <edgesGeometry args={[new THREE.OctahedronGeometry(1.501, 0)]} />
        <lineBasicMaterial color="#ffffff" transparent opacity={0.8} />
      </lineSegments>

      {/* 4. 外层环境 - 增加对比度 */}
      <mesh ref={outerRef}>
        <icosahedronGeometry args={[2.2, 1]} />
        <meshBasicMaterial
          color={colors[0]}
          wireframe
          transparent
          opacity={0.15}
        />
      </mesh>
    </group>
  );
};

const SciFiCore: React.FC<SciFiCoreProps> = ({ emotion = 'neutral', isSpeaking, colors: colorsProp, emotionColor }) => {
  const emoConfig = EMOTIONS[emotion] || EMOTIONS.neutral;
  const resolvedColors = useMemo<[string, string, string, string]>(() => {
    const base = colorsProp || emoConfig.colors;
    return [emotionColor || base[0], base[1], base[2], base[3]];
  }, [colorsProp, emoConfig.colors, emotionColor]);

  return (
    <div className="w-full h-full relative flex items-center justify-center" style={{ minHeight: '500px', minWidth: '400px' }}>
      <Canvas
        camera={{ position: [5, 4, 7], fov: 40 }}
        style={{ width: '100%', height: '100%' }}
        gl={{ 
          antialias: true,
          alpha: true,
        }}
        onCreated={({ gl }) => {
          gl.toneMapping = THREE.ReinhardToneMapping;
        }}
      >
        <ambientLight intensity={0.4} />
        {/* 主光源：从侧上方打下，产生强烈的明暗交替 */}
        <directionalLight position={[10, 10, 5]} intensity={3.5} color="#ffffff" castShadow />
        {/* 补光：增加边缘轮廓感 */}
        <pointLight position={[-10, -5, 10]} intensity={1.5} color={resolvedColors[1]} />
        
        <Float speed={2} rotationIntensity={0.5} floatIntensity={0.5}>
          <CrystalPrism colors={resolvedColors} isSpeaking={isSpeaking} />
        </Float>
      </Canvas>
    </div>
  );
};

export default SciFiCore;
