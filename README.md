# 📊 SimCompanies Market Scanner

Application web interactive pour analyser les opportunités de profit sur le marché SimCompanies, construite avec **Streamlit** et déployée sur **GitHub & Streamlit Cloud**.

## 🎯 Fonctionnalités

- 🔍 **Scan multi-bâtiments** automatique
- 📈 **Calcul de profit maximal** par produit
- 💰 **Prix de vente optimal** en temps réel
- 📊 **Interface interactive** avec filtres
- ⚡ **Cache intelligent** des données API
- 🌐 **Accessible en ligne** via Streamlit Cloud

## 🚀 Déploiement sur Streamlit Cloud (5 minutes)

### Étape 1: Préparer votre répo GitHub

```bash
# Créez un nouveau repo sur GitHub et clonez-le
git clone https://github.com/VOTRE_USERNAME/simcompanies-scanner.git
cd simcompanies-scanner
```

### Étape 2: Préparer les fichiers locaux

Assurez-vous que vous avez:
- ✅ `streamlit_app.py` (déjà créé)
- ✅ `requirements.txt` (déjà créé)
- ✅ `database.json` (votre fichier de base de données)
- ✅ `.gitignore` (déjà créé)

### Étape 3: Pousser vers GitHub

```bash
# Depuis votre répertoire local
git add .
git commit -m "Initial commit: SimCompanies Market Scanner"
git branch -M main
git remote add origin https://github.com/VOTRE_USERNAME/simcompanies-scanner.git
git push -u origin main
```

### Étape 4: Déployer sur Streamlit Cloud

1. Allez sur [share.streamlit.io](https://share.streamlit.io)
2. Connectez-vous avec votre compte GitHub
3. Cliquez sur "New app"
4. Sélectionnez:
   - Repository: `votre-username/simcompanies-scanner`
   - Branch: `main`
   - Main file path: `streamlit_app.py`
5. Cliquez "Deploy" ✅

**Votre app sera disponible à:** `https://simcompanies-scanner-[RANDOM].streamlit.app`

## 💻 Utilisation locale

### Installation

```bash
# Cloner le repo
git clone https://github.com/VOTRE_USERNAME/simcompanies-scanner.git
cd simcompanies-scanner

# Créer un environnement virtuel
python -m venv venv

# Activer l'environnement
# Sur Windows:
venv\Scripts\activate
# Sur macOS/Linux:
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt
```

### Lancer l'app

```bash
streamlit run streamlit_app.py
```

L'app s'ouvre automatiquement sur `http://localhost:8501`

## 📁 Structure du projet

```
simcompanies-scanner/
├── streamlit_app.py       # Application principale
├── requirements.txt       # Dépendances Python
├── database.json         # Base de données SimCompanies
├── .gitignore           # Fichiers à ignorer
└── README.md            # Ce fichier
```

## 🔧 Configuration

Dans la barre latérale, vous pouvez personnaliser:

- **Bonus UI**: Votre bonus de vitesse de vente (1.0 - 2.0)
- **Quantité par lot**: Unités à analyser (défaut: 1)

## 📊 Résultats

L'app vous montre:

1. **Tableau de bord** avec les meilleures opportunités
2. **Détails** prix d'achat/vente optimal
3. **Profit/heure** estimé
4. **Temps de vente** pour chaque produit

## 🔄 Mise à jour des données

- Les **saturations du marché** se mettent à jour toutes les **5 minutes**
- La **base de données** est en cache **1 heure**
- Les **offres de marché** se mettent à jour toutes les **5 minutes**

Pour forcer une actualisation: `Ctrl+Shift+R` ou cliquez "Always rerun"

## 📝 Notes importantes

### Pour Streamlit Cloud:
- ✅ Versioning automatique lors de chaque `git push`
- ✅ Logs en direct disponibles
- ✅ URL partageable publiquement
- ⚠️ Assurez-vous que `database.json` est dans le repo

### API Rate Limiting:
- Délai de 0.5s entre les requêtes (respecte les limites SimCompanies)
- Cache des données pour réduire les appels

## 🐛 Dépannage

**Erreur: "database.json introuvable"**
→ Vérifiez que le fichier est dans le répertoire racine

**App lente?**
→ Attendez le cache (5 min) ou cliquez "Always rerun" dans Streamlit Cloud

**Erreur API?**
→ SimCompanies API peut être indisponible. Réessayez dans quelques minutes.

## 🔐 Sécurité

- Pas d'authentification requise
- Pas de données sensibles stockées
- Pas de credentials en dur dans le code

## 📚 Ressources

- [Streamlit Documentation](https://docs.streamlit.io)
- [Streamlit Cloud](https://streamlit.io/cloud)
- [GitHub Docs](https://docs.github.com)

## 💡 Améliorations futures

- [ ] Historique des scans
- [ ] Graphiques de tendances
- [ ] Export en CSV
- [ ] Notifications push
- [ ] Mode sombre avancé

## 📄 Licence

MIT - Libre d'utilisation

---

**Créé avec ❤️ pour SimCompanies**

Pour des questions ou des améliorations, créez une issue sur GitHub!
