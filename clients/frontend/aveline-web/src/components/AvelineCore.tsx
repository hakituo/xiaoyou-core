import React, { useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { MeshDistortMaterial, Sphere, Float } from '@react-three/drei';
import * as THREE from 'three';

export interface AvelineCoreProps {
  status: 'idle' | 'thinking' | 'speaking';
  audioLevel?: number; // 0 to 1
  emotionColor: string; // Dynamic emotion color (hex)
  className?: string;
}

const CoreSphere = ({ status, audioLevel = 0, emotionColor }: { status: string; audioLevel: number; emotionColor: string }) => {
  const meshRef = useRef<THREE.Mesh>(null);
  const materialRef = useRef<any>(null);
  
  // Create color objects
  const targetColor = new THREE.Color(emotionColor);

  useFrame((state) => {
    if (!meshRef.current || !materialRef.current) return;
    const time = state.clock.getElapsedTime();

    // Target values based on status
    let targetDistort = 0.3;
    let targetSpeed = 1.5;
    let targetScale = 1.0;
    
    // Status behavior logic
    if (status === 'idle') {
      targetDistort = 0.4;
      targetSpeed = 2.0;
    } else if (status === 'thinking') {
      targetDistort = 0.65; // More distortion
      targetSpeed = 5.0;  // Faster movement
    } else if (status === 'speaking') {
      targetDistort = 0.5;
      targetSpeed = 3.0;
      targetScale = 1.0 + (audioLevel * 0.4); 
    }

    // Smoothly interpolate material properties
    materialRef.current.distort = THREE.MathUtils.lerp(materialRef.current.distort, targetDistort, 0.05);
    materialRef.current.speed = THREE.MathUtils.lerp(materialRef.current.speed, targetSpeed, 0.05);
    
    // Smoothly interpolate color and emissive color
    materialRef.current.color.lerp(targetColor, 0.1);
    materialRef.current.emissive.lerp(targetColor, 0.1);

    // Apply scale (with spring-like smoothness)
    const currentScale = meshRef.current.scale.x;
    const nextScale = THREE.MathUtils.lerp(currentScale, targetScale, 0.1);
    meshRef.current.scale.setScalar(nextScale);

    // Rotation
    meshRef.current.rotation.x = time * 0.2;
    meshRef.current.rotation.y = time * 0.3;
  });

  return (
    <Sphere args={[1, 64, 64]} ref={meshRef}>
      <MeshDistortMaterial
        ref={materialRef}
        color={emotionColor}         // Initial color
        emissive={emotionColor}      // Initial emissive
        emissiveIntensity={2.5}      // High intensity for neon effect
        toneMapped={false}           // Preserve high saturation
        attach="material"
        distort={0.4} 
        speed={2}     
        roughness={0.2}
        metalness={0.8}
        radius={1}
      />
    </Sphere>
  );
};

// Background Glow Billboard
const BackingGlow = ({ color }: { color: string }) => {
  return (
    <mesh position={[0, 0, -2]}>
      <planeGeometry args={[5, 5]} />
      <meshBasicMaterial 
        color={color} 
        transparent 
        opacity={0.4} 
        blending={THREE.AdditiveBlending}
        depthWrite={false}
      />
    </mesh>
  );
};

const AvelineCore: React.FC<AvelineCoreProps> = ({ 
  status, 
  audioLevel = 0, 
  emotionColor = "#ffffff",
  className 
}) => {
  return (
    <div className={`relative w-full h-full ${className || ''}`}>
      <Canvas 
        camera={{ position: [0, 0, 3], fov: 45 }} 
        dpr={[1, 2]}
        gl={{ alpha: true, antialias: true }} // Transparent background
        style={{ background: 'transparent' }} // Ensure canvas is transparent
      >
        <ambientLight intensity={0.5} />
        <pointLight position={[10, 10, 10]} intensity={1.5} color="#ffffff" />
        <pointLight position={[-10, -10, -5]} intensity={0.5} color={emotionColor} />
        
        {/* Backing Glow for visibility on transparent/bright backgrounds */}
        <BackingGlow color={emotionColor} />

        {/* Floating Core */}
        <Float 
          speed={status === 'thinking' ? 3 : 1.5} 
          rotationIntensity={status === 'thinking' ? 1.5 : 0.5} 
          floatIntensity={1}
        >
          <CoreSphere status={status} audioLevel={audioLevel} emotionColor={emotionColor} />
        </Float>
      </Canvas>
    </div>
  );
};

export default AvelineCore;
