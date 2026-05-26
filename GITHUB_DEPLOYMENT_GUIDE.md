# 🚀 GUIDE COMPLET: Déployer sur GitHub & Streamlit Cloud

## ⏱️ Temps estimé: 10-15 minutes

---

## ÉTAPE 1: Créer un compte GitHub (si nécessaire)

1. Allez sur [github.com](https://github.com)
2. Cliquez "Sign up"
3. Complétez l'inscription
4. Vérifiez votre email

---

## ÉTAPE 2: Créer un nouveau repository

### Via l'interface GitHub:

1. Connectez-vous sur GitHub
2. Cliquez le **`+`** en haut à droite → **"New repository"**
3. Remplissez:
   - **Repository name:** `simcompanies-scanner`
   - **Description:** "Market analyzer for SimCompanies"
   - **Visibility:** Public (pour Streamlit Cloud gratuit)
   - **Initialize with:** README ❌ (on l'a déjà)

4. Cliquez **"Create repository"** ✅

---

## ÉTAPE 3: Configurer Git localement

Ouvrez PowerShell dans votre dossier `C:\Users\julie\Desktop\SimCompanies\`

### Configurer Git (première fois seulement):

```powershell
git config --global user.name "Votre Nom"
git config --global user.email "votre.email@gmail.com"
```

### Initialiser le repo local:

```powershell
# Si Git n'est pas encore initialisé
git init

# Ou si le dossier a déjà un .git
git status
```

---

## ÉTAPE 4: Ajouter les fichiers & Pousser vers GitHub

```powershell
# Vérifier les fichiers à pusher
git status

# Ajouter tous les fichiers
git add .

# Créer un commit
git commit -m "Initial commit: SimCompanies Market Scanner with Streamlit"

# Renommer la branche principale (si nécessaire)
git branch -M main

# Ajouter l'URL distante (remplacez YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/simcompanies-scanner.git

# Pousser vers GitHub
git push -u origin main
```

**Vous devrez entrer:**
- **Username:** Votre nom d'utilisateur GitHub
- **Password:** Un Personal Access Token (voir étape 4b)

### 4b: Créer un Personal Access Token (PAT)

Si vous n'avez pas de PAT:

1. Sur GitHub → **Settings** (en bas à gauche)
2. → **Developer settings** (à gauche)
3. → **Personal access tokens** → **Tokens (classic)**
4. → **Generate new token (classic)**
5. Paramètres:
   - **Note:** "Git CLI"
   - **Expiration:** 90 days (ou plus)
   - **Scopes:** Cochez ✅ **`repo`** (full control of private repositories)
6. **Generate token** et **copiez-le** (c'est votre password Git)

---

## ÉTAPE 5: Vérifier le push sur GitHub

1. Allez sur [github.com/YOUR_USERNAME/simcompanies-scanner](https://github.com)
2. Vous devriez voir tous vos fichiers:
   - ✅ `streamlit_app.py`
   - ✅ `requirements.txt`
   - ✅ `database.json`
   - ✅ `README.md`
   - ✅ `.gitignore`

---

## ÉTAPE 6: Déployer sur Streamlit Cloud

### 6a: S'inscrire à Streamlit Cloud

1. Allez sur [share.streamlit.io](https://share.streamlit.io)
2. Cliquez **"Sign in with GitHub"** (à droite)
3. Autorisez l'accès
4. Remplissez le formulaire d'inscription

### 6b: Déployer l'app

1. Sur Streamlit Cloud, cliquez **"New app"** (bleu en haut à gauche)
2. Sélectionnez:
   - **Repository:** `YOUR_USERNAME/simcompanies-scanner`
   - **Branch:** `main`
   - **Main file path:** `streamlit_app.py`
3. Cliquez **"Deploy"** ✅

⏳ **Attendre 1-2 minutes** pour le déploiement...

### 6c: Accéder à votre app

Une fois déployée, vous recevrez une URL du type:
```
https://simcompanies-scanner-abc123.streamlit.app
```

✅ **C'est fait! Votre app est en ligne!**

---

## ÉTAPE 7: Mises à jour futures

Pour mettre à jour l'app en ligne:

```powershell
# Faire vos changements localement
# (modifier streamlit_app.py, etc.)

# Puis:
git add .
git commit -m "Description de vos changements"
git push origin main
```

**Streamlit Cloud redéploie automatiquement en ~1 minute!**

---

## 🔧 Dépannage

### Erreur: "database.json not found"
→ Assurez-vous que `database.json` est dans le repo GitHub

### Erreur de connexion Git
→ Vérifiez votre Personal Access Token dans le Settings GitHub

### App plantée après déploiement
→ Allez sur Streamlit Cloud → **Manage app** → **Settings** → Vérifiez les logs

### Veux voir les logs?
→ Sur Streamlit Cloud: cliquez **"Manage app"** → **Logs**

---

## 📊 Utilisation de votre app en ligne

1. Ouvrez le lien partageable
2. Attendez le chargement initial
3. Cliquez **"🔍 LANCER LE SCAN"**
4. Consultez les résultats!

---

## 🎉 Vous avez réussi!

Votre app est maintenant:
- ✅ Versionée sur GitHub
- ✅ Accessible au monde entier
- ✅ Mise à jour automatiquement
- ✅ Gratuite sur Streamlit Cloud

**Partagez l'URL avec vos amis!** 🚀

---

## 💡 Prochaines étapes (optionnel)

1. **Ajouter un favicon personnalisé**
2. **Customiser les couleurs**
3. **Ajouter des graphiques avancés**
4. **Exporter en CSV**

---

Pour toute question: consultez le README.md ou les docs Streamlit! 📚
