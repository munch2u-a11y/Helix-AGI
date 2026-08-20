/* -------------------------------------------------------------------
   Helix Subconscious Over-Agent — Real-Time 3D WebGL Helix Mascot Character
   Refined Procedural 3D Geometry: Mobius Figure-8 Double-Helix Ribbon Body,
   Character Head, Top Antennae, Expressive Face, Metallic Shaders & Mouse Follow.
------------------------------------------------------------------- */

class Helix3DMascot {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) return;

        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
        this.camera.position.set(0, 0, 13);

        this.renderer = new THREE.WebGLRenderer({
            canvas: this.canvas,
            alpha: true,
            antialias: true
        });
        this.renderer.setSize(180, 220);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

        this.targetMouse = new THREE.Vector2(0, 0);
        this.currentMouse = new THREE.Vector2(0, 0);
        this.time = 0;

        this.moodColors = {
            focused: { primary: 0x00F0FF, secondary: 0x7000FF },
            excited: { primary: 0xFF007A, secondary: 0xFFB800 },
            calm: { primary: 0x00FF99, secondary: 0x00F0FF },
            reflective: { primary: 0xE000FF, secondary: 0x4B0082 }
        };

        this.initLights();
        this.buildOfficial3DHelixLogoCharacter();
        this.initMouseEvents();
        this.animate();
    }

    initLights() {
        this.ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
        this.scene.add(this.ambientLight);

        this.primaryLight = new THREE.PointLight(0x00F0FF, 3.5, 25);
        this.primaryLight.position.set(5, 5, 8);
        this.scene.add(this.primaryLight);

        this.secondaryLight = new THREE.PointLight(0x7000FF, 2.5, 25);
        this.secondaryLight.position.set(-5, -5, 6);
        this.scene.add(this.secondaryLight);

        const dirLight = new THREE.DirectionalLight(0xffffff, 0.9);
        dirLight.position.set(0, 10, 10);
        this.scene.add(dirLight);
    }

    buildOfficial3DHelixLogoCharacter() {
        this.characterGroup = new THREE.Group();
        this.scene.add(this.characterGroup);

        // 1. 3D Figure-8 / Mobius Interlocking Double-Helix Ribbon Body
        this.helixGroup = new THREE.Group();
        this.characterGroup.add(this.helixGroup);

        const createMobiusStrand = (phaseOffset, mainHex, emissiveHex) => {
            const points = [];
            const steps = 80;

            for (let i = 0; i <= steps; i++) {
                const u = (i / steps) * Math.PI * 2;
                // Parametric Figure-8 / Double Loop Curve
                const scale = 2.2;
                const x = scale * Math.sin(u);
                const y = scale * Math.sin(u) * Math.cos(u) * 1.5 - 0.4;
                const z = scale * Math.cos(u * 2 + phaseOffset) * 0.6;
                points.push(new THREE.Vector3(x, y, z));
            }

            const curve = new THREE.CatmullRomCurve3(points);
            const tubeGeo = new THREE.TubeGeometry(curve, 80, 0.22, 14, true);
            const tubeMat = new THREE.MeshStandardMaterial({
                color: mainHex,
                metalness: 0.88,
                roughness: 0.18,
                emissive: emissiveHex,
                emissiveIntensity: 0.35
            });

            return new THREE.Mesh(tubeGeo, tubeMat);
        };

        this.strandA = createMobiusStrand(0, 0x00F0FF, 0x00F0FF);
        this.strandB = createMobiusStrand(Math.PI, 0x7000FF, 0x7000FF);
        this.helixGroup.add(this.strandA);
        this.helixGroup.add(this.strandB);

        // 3D DNA Base-Pair Rungs & Spheres in Lower Loop
        for (let i = 0; i < 5; i++) {
            const y = -1.2 - i * 0.45;
            const width = 1.6 - i * 0.15;

            const p1 = new THREE.Vector3(-width / 2, y, 0);
            const p2 = new THREE.Vector3(width / 2, y, 0);

            const rungCurve = new THREE.LineCurve3(p1, p2);
            const rungGeo = new THREE.TubeGeometry(rungCurve, 2, 0.07, 8, false);
            const rungMat = new THREE.MeshStandardMaterial({
                color: 0x00F0FF,
                metalness: 0.9,
                emissive: 0x00F0FF,
                emissiveIntensity: 0.4
            });
            this.helixGroup.add(new THREE.Mesh(rungGeo, rungMat));

            // Small glowing sphere on rung ends
            const sphereGeo = new THREE.SphereGeometry(0.12, 12, 12);
            const sphereMat = new THREE.MeshBasicMaterial({ color: 0x00F0FF });
            const s1 = new THREE.Mesh(sphereGeo, sphereMat);
            s1.position.copy(p1);
            const s2 = new THREE.Mesh(sphereGeo, sphereMat);
            s2.position.copy(p2);
            this.helixGroup.add(s1);
            this.helixGroup.add(s2);
        }

        // 2. 3D Character Head Sphere & Core (Framed in Upper Ribbon Loop)
        this.headGroup = new THREE.Group();
        this.headGroup.position.set(0, 1.4, 0);
        this.characterGroup.add(this.headGroup);

        const headGeo = new THREE.SphereGeometry(1.35, 32, 32);
        this.headMat = new THREE.MeshStandardMaterial({
            color: 0x101622,
            metalness: 0.75,
            roughness: 0.2,
            emissive: 0x00F0FF,
            emissiveIntensity: 0.25
        });
        this.headMesh = new THREE.Mesh(headGeo, this.headMat);
        this.headGroup.add(this.headMesh);

        // Inner Glowing Crystal Core
        const coreGeo = new THREE.IcosahedronGeometry(0.6, 1);
        this.coreMat = new THREE.MeshBasicMaterial({ color: 0x00F0FF });
        this.coreMesh = new THREE.Mesh(coreGeo, this.coreMat);
        this.headGroup.add(this.coreMesh);

        // 3D Top Antennae
        const createAntenna = (xOffset) => {
            const group = new THREE.Group();
            const stemGeo = new THREE.CylinderGeometry(0.045, 0.045, 0.75, 8);
            const stemMat = new THREE.MeshStandardMaterial({ color: 0x00F0FF, metalness: 0.9 });
            const stem = new THREE.Mesh(stemGeo, stemMat);
            stem.position.y = 1.55;
            stem.position.x = xOffset;
            stem.rotation.z = -xOffset * 0.45;
            group.add(stem);

            const tipGeo = new THREE.SphereGeometry(0.14, 16, 16);
            this.tipMat = new THREE.MeshBasicMaterial({ color: 0x00F0FF });
            const tip = new THREE.Mesh(tipGeo, this.tipMat);
            tip.position.set(xOffset * 1.35, 1.9, 0);
            group.add(tip);

            return group;
        };

        this.headGroup.add(createAntenna(-0.42));
        this.headGroup.add(createAntenna(0.42));

        // 3. 3D Expressive Eyes & Smile
        this.eyeGroup = new THREE.Group();
        this.eyeGroup.position.set(0, 0.1, 1.26);
        this.headGroup.add(this.eyeGroup);

        const eyeGeo = new THREE.SphereGeometry(0.19, 16, 16);
        this.eyeMat = new THREE.MeshBasicMaterial({ color: 0xFFFFFF });

        this.eyeLeft = new THREE.Mesh(eyeGeo, this.eyeMat);
        this.eyeLeft.position.set(-0.44, 0, 0);
        this.eyeLeft.scale.set(1, 1.25, 0.4);

        this.eyeRight = new THREE.Mesh(eyeGeo, this.eyeMat);
        this.eyeRight.position.set(0.44, 0, 0);
        this.eyeRight.scale.set(1, 1.25, 0.4);

        this.eyeGroup.add(this.eyeLeft);
        this.eyeGroup.add(this.eyeRight);

        // Smile Curve
        const mouthCurve = new THREE.QuadraticBezierCurve3(
            new THREE.Vector3(-0.28, -0.34, 1.28),
            new THREE.Vector3(0, -0.52, 1.31),
            new THREE.Vector3(0.28, -0.34, 1.28)
        );
        const mouthGeo = new THREE.TubeGeometry(mouthCurve, 16, 0.045, 8, false);
        this.mouthMat = new THREE.MeshBasicMaterial({ color: 0xFFFFFF });
        this.mouthMesh = new THREE.Mesh(mouthGeo, this.mouthMat);
        this.headGroup.add(this.mouthMesh);
    }

    initMouseEvents() {
        window.addEventListener("mousemove", (e) => {
            const x = (e.clientX / window.innerWidth) * 2 - 1;
            const y = -(e.clientY / window.innerHeight) * 2 + 1;
            this.targetMouse.set(x, y);
        });
    }

    setMood(moodName) {
        const mood = this.moodColors[moodName] || this.moodColors.focused;

        this.primaryLight.color.setHex(mood.primary);
        this.secondaryLight.color.setHex(mood.secondary);
        this.strandA.material.color.setHex(mood.primary);
        this.strandA.material.emissive.setHex(mood.primary);
        this.strandB.material.color.setHex(mood.secondary);
        this.strandB.material.emissive.setHex(mood.secondary);
        this.coreMat.color.setHex(mood.primary);
        this.tipMat.color.setHex(mood.primary);
    }

    animate() {
        requestAnimationFrame(() => this.animate());
        this.time += 0.025;

        this.currentMouse.lerp(this.targetMouse, 0.05);

        // 3D Floating Bobbing & Rotation
        if (this.characterGroup) {
            this.characterGroup.position.y = Math.sin(this.time) * 0.22;
            this.characterGroup.rotation.y = Math.sin(this.time * 0.5) * 0.12;
            this.characterGroup.rotation.x = this.currentMouse.y * 0.22;
            this.characterGroup.rotation.y += this.currentMouse.x * 0.32;
        }

        // Rotate Mobius Ribbon Strands
        if (this.helixGroup) {
            this.helixGroup.rotation.y += 0.012;
        }

        // Pulse Core Crystal
        if (this.coreMesh) {
            this.coreMesh.rotation.x += 0.02;
            this.coreMesh.rotation.y += 0.03;
            const scale = 1 + Math.sin(this.time * 3) * 0.15;
            this.coreMesh.scale.set(scale, scale, scale);
        }

        this.renderer.render(this.scene, this.camera);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    window.helix3DMascot = new Helix3DMascot("helix-3d-canvas");
});
