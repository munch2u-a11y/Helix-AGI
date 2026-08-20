/* -------------------------------------------------------------------
   Helix Subconscious Over-Agent — Real-Time 3D WebGL Mascot Character
   Renders true 3D procedural double-helix DNA body, glowing head,
   top antennae, expressive 3D face, interactive mouse tracking, and lighting.
------------------------------------------------------------------- */

class Helix3DMascot {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) return;

        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
        this.camera.position.set(0, 0, 12);

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
        this.currentMood = "focused";

        this.initLights();
        this.build3DHelixCharacter();
        this.initMouseEvents();
        this.animate();
    }

    initLights() {
        this.ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
        this.scene.add(this.ambientLight);

        this.primaryLight = new THREE.PointLight(0x00F0FF, 3, 20);
        this.primaryLight.position.set(4, 4, 6);
        this.scene.add(this.primaryLight);

        this.secondaryLight = new THREE.PointLight(0x7000FF, 2, 20);
        this.secondaryLight.position.set(-4, -4, 4);
        this.scene.add(this.secondaryLight);

        const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
        dirLight.position.set(0, 10, 10);
        this.scene.add(dirLight);
    }

    build3DHelixCharacter() {
        this.characterGroup = new THREE.Group();
        this.scene.add(this.characterGroup);

        // 1. 3D Double-Helix Spiral DNA Body
        this.helixGroup = new THREE.Group();
        this.characterGroup.add(this.helixGroup);

        const createStrand = (offsetPhase, colorHex) => {
            const points = [];
            const height = 4.5;
            const turns = 2.0;
            const radius = 1.2;

            for (let i = 0; i <= 60; i++) {
                const t = i / 60;
                const y = (t - 0.5) * height - 0.8;
                const angle = t * Math.PI * 2 * turns + offsetPhase;
                const x = Math.cos(angle) * radius;
                const z = Math.sin(angle) * radius;
                points.push(new THREE.Vector3(x, y, z));
            }

            const curve = new THREE.CatmullRomCurve3(points);
            const geometry = new THREE.TubeGeometry(curve, 60, 0.18, 12, false);
            const material = new THREE.MeshStandardMaterial({
                color: colorHex,
                metalness: 0.85,
                roughness: 0.2,
                emissive: colorHex,
                emissiveIntensity: 0.3
            });

            return new THREE.Mesh(geometry, material);
        };

        this.strandA = createStrand(0, 0x00F0FF);
        this.strandB = createStrand(Math.PI, 0x7000FF);
        this.helixGroup.add(this.strandA);
        this.helixGroup.add(this.strandB);

        // 3D Connecting Base Pair Rungs
        for (let i = 0; i < 7; i++) {
            const t = i / 6;
            const y = (t - 0.5) * 4.0 - 0.8;
            const angle = t * Math.PI * 2 * 2.0;
            const r1 = 1.1;

            const x1 = Math.cos(angle) * r1;
            const z1 = Math.sin(angle) * r1;
            const x2 = Math.cos(angle + Math.PI) * r1;
            const z2 = Math.sin(angle + Math.PI) * r1;

            const p1 = new THREE.Vector3(x1, y, z1);
            const p2 = new THREE.Vector3(x2, y, z2);

            const rungCurve = new THREE.LineCurve3(p1, p2);
            const rungGeo = new THREE.TubeGeometry(rungCurve, 2, 0.06, 8, false);
            const rungMat = new THREE.MeshStandardMaterial({
                color: 0x00F0FF,
                metalness: 0.9,
                roughness: 0.1,
                emissive: 0x00F0FF,
                emissiveIntensity: 0.4
            });
            this.helixGroup.add(new THREE.Mesh(rungGeo, rungMat));
        }

        // 2. 3D Character Head Sphere & Core
        this.headGroup = new THREE.Group();
        this.headGroup.position.set(0, 1.6, 0);
        this.characterGroup.add(this.headGroup);

        const headGeo = new THREE.SphereGeometry(1.3, 32, 32);
        this.headMat = new THREE.MeshStandardMaterial({
            color: 0x101622,
            metalness: 0.7,
            roughness: 0.25,
            emissive: 0x00F0FF,
            emissiveIntensity: 0.2
        });
        this.headMesh = new THREE.Mesh(headGeo, this.headMat);
        this.headGroup.add(this.headMesh);

        // 3D Glowing Inner Core Crystal
        const coreGeo = new THREE.IcosahedronGeometry(0.55, 1);
        this.coreMat = new THREE.MeshBasicMaterial({
            color: 0x00F0FF,
            wireframe: false
        });
        this.coreMesh = new THREE.Mesh(coreGeo, this.coreMat);
        this.headGroup.add(this.coreMesh);

        // 3D Antennae (Top of Head)
        const createAntenna = (xOffset) => {
            const group = new THREE.Group();
            const stemGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.7, 8);
            const stemMat = new THREE.MeshStandardMaterial({ color: 0x00F0FF, metalness: 0.9 });
            const stem = new THREE.Mesh(stemGeo, stemMat);
            stem.position.y = 1.5;
            stem.position.x = xOffset;
            stem.rotation.z = -xOffset * 0.4;
            group.add(stem);

            const tipGeo = new THREE.SphereGeometry(0.12, 16, 16);
            this.tipMat = new THREE.MeshBasicMaterial({ color: 0x00F0FF });
            const tip = new THREE.Mesh(tipGeo, this.tipMat);
            tip.position.set(xOffset * 1.3, 1.85, 0);
            group.add(tip);

            return group;
        };

        this.headGroup.add(createAntenna(-0.4));
        this.headGroup.add(createAntenna(0.4));

        // 3. 3D Expressive Eyes
        this.eyeGroup = new THREE.Group();
        this.eyeGroup.position.set(0, 0.1, 1.22);
        this.headGroup.add(this.eyeGroup);

        const eyeGeo = new THREE.SphereGeometry(0.18, 16, 16);
        this.eyeMat = new THREE.MeshBasicMaterial({ color: 0xFFFFFF });

        this.eyeLeft = new THREE.Mesh(eyeGeo, this.eyeMat);
        this.eyeLeft.position.set(-0.42, 0, 0);
        this.eyeLeft.scale.set(1, 1.2, 0.4);

        this.eyeRight = new THREE.Mesh(eyeGeo, this.eyeMat);
        this.eyeRight.position.set(0.42, 0, 0);
        this.eyeRight.scale.set(1, 1.2, 0.4);

        this.eyeGroup.add(this.eyeLeft);
        this.eyeGroup.add(this.eyeRight);

        // 3D Smiling Mouth Curve
        const mouthCurve = new THREE.QuadraticBezierCurve3(
            new THREE.Vector3(-0.25, -0.32, 1.24),
            new THREE.Vector3(0, -0.48, 1.27),
            new THREE.Vector3(0.25, -0.32, 1.24)
        );
        const mouthGeo = new THREE.TubeGeometry(mouthCurve, 16, 0.04, 8, false);
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
        this.currentMood = moodName;

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

        // Smooth mouse tracking interpolation
        this.currentMouse.lerp(this.targetMouse, 0.05);

        // 3D Floating Bobbing & Rotation
        if (this.characterGroup) {
            this.characterGroup.position.y = Math.sin(this.time) * 0.25;
            this.characterGroup.rotation.y = Math.sin(this.time * 0.5) * 0.15;
            this.characterGroup.rotation.x = this.currentMouse.y * 0.2;
            this.characterGroup.rotation.y += this.currentMouse.x * 0.3;
        }

        // Rotate Double-Helix Body Strands
        if (this.helixGroup) {
            this.helixGroup.rotation.y += 0.015;
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
