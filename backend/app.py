import os, secrets, io
from datetime import datetime, date, timedelta
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from openpyxl import load_workbook, Workbook

db=SQLAlchemy()

class Member(db.Model):
    __tablename__="members"
    id=db.Column(db.Integer,primary_key=True)
    first_name=db.Column(db.String(100),nullable=False)
    last_name=db.Column(db.String(100),nullable=False)
    company=db.Column(db.String(180))
    activity=db.Column(db.String(180))
    email=db.Column(db.String(180),index=True)
    phone=db.Column(db.String(50))
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class UserAccount(db.Model):
    __tablename__="user_accounts"
    id=db.Column(db.Integer,primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,unique=True,index=True)
    email=db.Column(db.String(180),nullable=False,unique=True,index=True)
    password_hash=db.Column(db.String(255))
    status=db.Column(db.String(30),nullable=False,default="INVITED")
    invitation_token=db.Column(db.String(128),unique=True,index=True)
    invitation_expires_at=db.Column(db.DateTime)
    activated_at=db.Column(db.DateTime)
    is_system_admin=db.Column(db.Boolean,nullable=False,default=False)
    member=db.relationship("Member",backref=db.backref("user_account",uselist=False))

class AuthSession(db.Model):
    __tablename__="auth_sessions"
    id=db.Column(db.Integer,primary_key=True)
    account_id=db.Column(db.Integer,db.ForeignKey("user_accounts.id"),nullable=False,index=True)
    token_hash=db.Column(db.String(64),nullable=False,unique=True,index=True)
    expires_at=db.Column(db.DateTime,nullable=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)
    account=db.relationship("UserAccount")

class Membership(db.Model):
    __tablename__="memberships"
    id=db.Column(db.Integer,primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    start_date=db.Column(db.Date)
    end_date=db.Column(db.Date)
    status=db.Column(db.String(30),nullable=False,default="ACTIVE")
    member=db.relationship("Member",backref="memberships")

class Mandate(db.Model):
    __tablename__="mandates"
    id=db.Column(db.Integer,primary_key=True)
    name=db.Column(db.String(120),nullable=False)
    start_date=db.Column(db.Date,nullable=False)
    end_date=db.Column(db.Date,nullable=False)
    status=db.Column(db.String(30),nullable=False,default="PREPARATION")

class Role(db.Model):
    __tablename__="roles"
    id=db.Column(db.Integer,primary_key=True)
    name=db.Column(db.String(120),nullable=False,unique=True)

class RoleAssignment(db.Model):
    __tablename__="role_assignments"
    id=db.Column(db.Integer,primary_key=True)
    mandate_id=db.Column(db.Integer,db.ForeignKey("mandates.id"),nullable=False)
    role_id=db.Column(db.Integer,db.ForeignKey("roles.id"),nullable=False)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False)
    status=db.Column(db.String(30),nullable=False,default="ACTIVE")

class ImportLog(db.Model):
    __tablename__="import_logs"
    id=db.Column(db.Integer,primary_key=True)
    account_id=db.Column(db.Integer,db.ForeignKey("user_accounts.id"),nullable=False,index=True)
    filename=db.Column(db.String(255))
    created_count=db.Column(db.Integer,nullable=False,default=0)
    updated_count=db.Column(db.Integer,nullable=False,default=0)
    error_count=db.Column(db.Integer,nullable=False,default=0)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)
    account=db.relationship("UserAccount")

class Meeting(db.Model):
    __tablename__="meetings"
    id=db.Column(db.Integer,primary_key=True)
    date=db.Column(db.Date,nullable=False,index=True)
    start_time=db.Column(db.Time)
    type=db.Column(db.String(40),nullable=False,default="REGULAR")
    location=db.Column(db.String(180))
    status=db.Column(db.String(30),nullable=False,default="PLANNED")
    notes=db.Column(db.Text)

def create_app():
    app=Flask(__name__)
    database_url=os.getenv("DATABASE_URL","sqlite:///bni_dev.db")
    if database_url.startswith("postgres://"):
        database_url=database_url.replace("postgres://","postgresql://",1)
    app.config["SQLALCHEMY_DATABASE_URI"]=database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
    db.init_app(app)
    CORS(app,origins=os.getenv("CORS_ORIGINS","https://cx-labs.be").split(","))

    @app.get("/health")
    def health():
        return {"status":"ok","service":"bni-soignies-api"}

    @app.get("/api")
    def api():
        return {"name":"BNI Soignies Hub API","version":"0.1.0"}

    def require_admin():
        account,_=bearer_account()
        if not account:return None,({"error":"Authentification requise."},401)
        if not account_payload(account)["isAdmin"]:return None,({"error":"Accès administrateur requis."},403)
        return account,None

    def member_payload(m):
        membership=Membership.query.filter_by(member_id=m.id).order_by(Membership.id.desc()).first()
        account=m.user_account
        return {"id":m.id,"firstName":m.first_name,"lastName":m.last_name,"company":m.company,"activity":m.activity,"email":m.email,"phone":m.phone,"status":membership.status if membership else None,"startDate":membership.start_date.isoformat() if membership and membership.start_date else None,"endDate":membership.end_date.isoformat() if membership and membership.end_date else None,"accountStatus":account.status if account else "NO_ACCOUNT","isSystemAdmin":bool(account and account.is_system_admin)}

    @app.route("/api/members",methods=["GET","POST"])
    def members():
        _,auth_error=require_admin()
        if auth_error:return auth_error
        if request.method=="POST":
            data=request.get_json(silent=True) or {}
            first=(data.get("firstName") or "").strip()
            last=(data.get("lastName") or "").strip()
            if not first or not last:
                return {"error":"firstName and lastName are required"},400
            email=(data.get("email") or "").strip() or None
            duplicate=Member.query.filter(db.func.lower(Member.first_name)==first.lower(),db.func.lower(Member.last_name)==last.lower()).first()
            if duplicate:
                return {"error":"Un membre avec ce prénom et ce nom existe déjà.","duplicateId":duplicate.id},409
            if email and Member.query.filter(db.func.lower(Member.email)==email.lower()).first():
                return {"error":"Un membre avec cet e-mail existe déjà."},409
            member=Member(first_name=first,last_name=last,company=(data.get("company") or "").strip() or None,activity=(data.get("activity") or "").strip() or None,email=email,phone=(data.get("phone") or "").strip() or None)
            db.session.add(member)
            db.session.flush()
            membership=Membership(member_id=member.id,start_date=date.today(),status="ACTIVE")
            db.session.add(membership)
            db.session.commit()
            return {"id":member.id,"firstName":member.first_name,"lastName":member.last_name,"company":member.company,"activity":member.activity,"email":member.email,"phone":member.phone,"status":"ACTIVE"},201
        rows=Member.query.order_by(Member.last_name,Member.first_name).all()
        return jsonify([member_payload(m) for m in rows])

    @app.route("/api/members/<int:member_id>",methods=["GET","PATCH"])
    def member_detail(member_id):
        _,auth_error=require_admin()
        if auth_error:return auth_error
        member=db.session.get(Member,member_id)
        if not member:return {"error":"Membre introuvable."},404
        if request.method=="GET":return member_payload(member)
        data=request.get_json(silent=True) or {}
        for key,attr in [("firstName","first_name"),("lastName","last_name"),("company","company"),("activity","activity"),("phone","phone")]:
            if key in data:setattr(member,attr,(data.get(key) or "").strip() or None)
        if not member.first_name or not member.last_name:return {"error":"Prénom et nom obligatoires."},400
        if "email" in data:
            email=(data.get("email") or "").strip().lower() or None
            other=Member.query.filter(Member.id!=member.id,db.func.lower(Member.email)==email).first() if email else None
            if other:return {"error":"Cette adresse e-mail appartient déjà à un autre membre."},409
            if member.user_account and email and member.user_account.email.lower()!=email:
                used=UserAccount.query.filter(UserAccount.id!=member.user_account.id,db.func.lower(UserAccount.email)==email).first()
                if used:return {"error":"Cette adresse e-mail est déjà liée à un autre compte."},409
                member.user_account.email=email
            member.email=email
        membership=Membership.query.filter_by(member_id=member.id).order_by(Membership.id.desc()).first()
        if not membership:
            membership=Membership(member_id=member.id,status="ACTIVE");db.session.add(membership)
        if "status" in data:membership.status=data["status"]
        if "startDate" in data:membership.start_date=date.fromisoformat(data["startDate"]) if data["startDate"] else None
        if "endDate" in data:membership.end_date=date.fromisoformat(data["endDate"]) if data["endDate"] else None
        db.session.commit()
        return member_payload(member)

    def parse_member_excel(file):
        wb=load_workbook(io.BytesIO(file.read()),read_only=True,data_only=True)
        ws=wb.active
        rows=list(ws.iter_rows(values_only=True))
        if not rows:return [],[],["Le fichier est vide."]
        aliases={"prenom":"firstName","prénom":"firstName","nom":"lastName","societe":"company","société":"company","entreprise":"company","activite":"activity","activité":"activity","email":"email","e-mail":"email","mail":"email","telephone":"phone","téléphone":"phone","gsm":"phone","date entree":"startDate","date d'entrée":"startDate","date entrée":"startDate","statut":"status"}
        import unicodedata
        def norm(v):
            s=str(v or "").strip().lower()
            return " ".join(s.split())
        headers=[norm(v) for v in rows[0]]
        mapping={i:aliases[h] for i,h in enumerate(headers) if h in aliases}
        if "firstName" not in mapping.values() or "lastName" not in mapping.values():
            return [],[],["Colonnes Prénom et Nom obligatoires."]
        preview=[];errors=[]
        for n,row in enumerate(rows[1:],start=2):
            data={}
            for i,key in mapping.items():
                if i>=len(row):continue
                v=row[i]
                if hasattr(v,"isoformat") and key=="startDate":v=v.date().isoformat() if hasattr(v,"date") else v.isoformat()
                data[key]=str(v).strip() if v is not None else ""
            if not data.get("firstName") and not data.get("lastName"):continue
            if not data.get("firstName") or not data.get("lastName"):
                errors.append(f"Ligne {n}: prénom ou nom manquant.");continue
            existing=Member.query.filter(db.func.lower(Member.first_name)==data["firstName"].lower(),db.func.lower(Member.last_name)==data["lastName"].lower()).first()
            data["row"]=n;data["action"]="UPDATE" if existing else "CREATE";data["existingId"]=existing.id if existing else None
            preview.append(data)
        return preview,[{"column":headers[i],"field":key} for i,key in mapping.items()],errors

    @app.post("/api/members/import/preview")
    def import_members_preview():
        _,auth_error=require_admin()
        if auth_error:return auth_error
        file=request.files.get("file")
        if not file or not file.filename.lower().endswith(".xlsx"):return {"error":"Fichier .xlsx requis."},400
        try: preview,mapping,errors=parse_member_excel(file)
        except Exception:return {"error":"Impossible de lire ce fichier Excel."},400
        return {"rows":preview,"mapping":mapping,"errors":errors,"summary":{"total":len(preview),"create":sum(x["action"]=="CREATE" for x in preview),"update":sum(x["action"]=="UPDATE" for x in preview)}}

    @app.post("/api/members/import/confirm")
    def import_members_confirm():
        _,auth_error=require_admin()
        if auth_error:return auth_error
        data=request.get_json(silent=True) or {}
        rows=data.get("rows") or []
        created=updated=0
        for item in rows:
            first=(item.get("firstName") or "").strip();last=(item.get("lastName") or "").strip()
            if not first or not last:continue
            member=Member.query.filter(db.func.lower(Member.first_name)==first.lower(),db.func.lower(Member.last_name)==last.lower()).first()
            if member:updated+=1
            else:
                member=Member(first_name=first,last_name=last);db.session.add(member);db.session.flush();created+=1
            for key,attr in [("company","company"),("activity","activity"),("email","email"),("phone","phone")]:
                if item.get(key):setattr(member,attr,str(item[key]).strip())
            membership=Membership.query.filter_by(member_id=member.id).order_by(Membership.id.desc()).first()
            if not membership:membership=Membership(member_id=member.id,status="ACTIVE");db.session.add(membership)
            if item.get("startDate"):
                try:membership.start_date=date.fromisoformat(str(item["startDate"])[:10])
                except ValueError:pass
            status=(item.get("status") or "").strip().upper()
            if status in {"ACTIVE","ONBOARDING","FORMER"}:membership.status=status
        account,_=bearer_account()
        log=ImportLog(account_id=account.id,filename=(data.get("filename") or "import.xlsx")[:255],created_count=created,updated_count=updated,error_count=0)
        db.session.add(log)
        db.session.commit()
        return {"status":"ok","created":created,"updated":updated}

    @app.get("/api/members/import/history")
    def import_members_history():
        _,auth_error=require_admin()
        if auth_error:return auth_error
        rows=ImportLog.query.order_by(ImportLog.created_at.desc()).limit(50).all()
        return jsonify([{"id":x.id,"filename":x.filename,"created":x.created_count,"updated":x.updated_count,"errors":x.error_count,"createdAt":x.created_at.isoformat(),"by":f"{x.account.member.first_name} {x.account.member.last_name}"} for x in rows])

    @app.get("/api/members/export")
    def export_members():
        _,auth_error=require_admin()
        if auth_error:return auth_error
        wb=Workbook();ws=wb.active;ws.title="Membres"
        ws.append(["Prénom","Nom","Société","Activité","Email","Téléphone","Date entrée","Date sortie","Statut","Accès Hub"])
        for m in Member.query.order_by(Member.last_name,Member.first_name).all():
            membership=Membership.query.filter_by(member_id=m.id).order_by(Membership.id.desc()).first()
            ws.append([m.first_name,m.last_name,m.company or "",m.activity or "",m.email or "",m.phone or "",membership.start_date if membership else None,membership.end_date if membership else None,membership.status if membership else "",m.user_account.status if m.user_account else "NO_ACCOUNT"])
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width=min(max(12,max(len(str(cell.value or "")) for cell in col)+2),40)
        out=io.BytesIO();wb.save(out);out.seek(0)
        return send_file(out,as_attachment=True,download_name=f"BNI-Soignies-Membres-{date.today().isoformat()}.xlsx",mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.post("/api/members/<int:member_id>/invite")
    def invite_member(member_id):
        _,auth_error=require_admin()
        if auth_error:return auth_error
        member=db.session.get(Member,member_id)
        if not member:
            return {"error":"Membre introuvable."},404
        if not member.email:
            return {"error":"Une adresse e-mail est nécessaire pour créer l'accès."},400
        existing=UserAccount.query.filter(db.func.lower(UserAccount.email)==member.email.lower()).first()
        if existing and existing.member_id!=member.id:
            return {"error":"Cette adresse e-mail est déjà liée à un autre compte."},409
        account=member.user_account or UserAccount(member_id=member.id,email=member.email.lower())
        account.email=member.email.lower()
        account.status="INVITED"
        account.invitation_token=secrets.token_urlsafe(32)
        account.invitation_expires_at=datetime.utcnow()+timedelta(hours=48)
        if not account.id: db.session.add(account)
        db.session.commit()
        base=os.getenv("APP_URL","https://cx-labs.be/Bnisoignies-hub/").rstrip("/")
        return {"status":"INVITED","activationUrl":f"{base}/?activate={account.invitation_token}","expiresInHours":48}

    @app.post("/api/auth/activate")
    def activate():
        data=request.get_json(silent=True) or {}
        token=(data.get("token") or "").strip()
        password=data.get("password") or ""
        if len(password)<10:
            return {"error":"Le mot de passe doit contenir au moins 10 caractères."},400
        account=UserAccount.query.filter_by(invitation_token=token).first()
        if not account or not account.invitation_expires_at or account.invitation_expires_at<datetime.utcnow():
            return {"error":"Lien d'activation invalide ou expiré."},400
        account.password_hash=generate_password_hash(password)
        account.status="ACTIVE"
        account.activated_at=datetime.utcnow()
        account.invitation_token=None
        account.invitation_expires_at=None
        db.session.commit()
        return {"status":"ACTIVE","message":"Compte activé."}

    def account_payload(account):
        today=date.today()
        active_mandates=Mandate.query.filter(Mandate.start_date<=today,Mandate.end_date>=today).all()
        mandate_ids=[m.id for m in active_mandates]
        roles=[]
        if mandate_ids:
            assignments=RoleAssignment.query.filter(RoleAssignment.member_id==account.member_id,RoleAssignment.mandate_id.in_(mandate_ids),RoleAssignment.status=="ACTIVE").all()
            role_ids=[a.role_id for a in assignments]
            if role_ids: roles=[r.name for r in Role.query.filter(Role.id.in_(role_ids)).all()]
        admin=bool(account.is_system_admin or any(r.lower() in {"président","president","vice-président","vice-president","secrétaire-trésorier","secretaire-tresorier"} for r in roles))
        return {"id":account.member.id,"firstName":account.member.first_name,"lastName":account.member.last_name,"email":account.email,"roles":roles,"isAdmin":admin}

    def bearer_account():
        header=request.headers.get("Authorization","")
        if not header.startswith("Bearer "): return None,None
        raw=header[7:].strip()
        import hashlib
        hashed=hashlib.sha256(raw.encode()).hexdigest()
        session=AuthSession.query.filter_by(token_hash=hashed).first()
        if not session or session.expires_at<datetime.utcnow():
            if session:
                db.session.delete(session);db.session.commit()
            return None,None
        return session.account,session

    @app.post("/api/auth/login")
    def login():
        data=request.get_json(silent=True) or {}
        email=(data.get("email") or "").strip().lower()
        account=UserAccount.query.filter(db.func.lower(UserAccount.email)==email).first()
        if not account or account.status!="ACTIVE" or not account.password_hash or not check_password_hash(account.password_hash,data.get("password") or ""):
            return {"error":"Identifiants incorrects."},401
        raw=secrets.token_urlsafe(48)
        import hashlib
        session=AuthSession(account_id=account.id,token_hash=hashlib.sha256(raw.encode()).hexdigest(),expires_at=datetime.utcnow()+timedelta(days=7))
        db.session.add(session);db.session.commit()
        return {"token":raw,"expiresInDays":7,"member":account_payload(account)}

    @app.get("/api/auth/me")
    def me():
        account,_=bearer_account()
        if not account:return {"error":"Session invalide ou expirée."},401
        return {"member":account_payload(account)}

    @app.post("/api/auth/logout")
    def logout():
        _,session=bearer_account()
        if session:
            db.session.delete(session);db.session.commit()
        return {"status":"ok"}

    @app.post("/api/system/bootstrap-xavier")
    def bootstrap_xavier():
        key=request.headers.get("X-Bootstrap-Key","")
        if not key or not secrets.compare_digest(key,os.getenv("BOOTSTRAP_KEY","disabled")):
            return {"error":"Forbidden"},403
        candidates=Member.query.filter(db.func.lower(Member.first_name)=="xavier",db.func.lower(Member.last_name)=="renaud").all()
        active=None
        for m in candidates:
            if m.user_account and m.user_account.status=="ACTIVE" and m.user_account.password_hash:
                active=m;break
        if not active:
            return {"error":"Aucun compte Xavier Renaud actif trouvé."},404
        active.user_account.is_system_admin=True
        membership=Membership.query.filter_by(member_id=active.id).order_by(Membership.id.asc()).first()
        if not membership:
            membership=Membership(member_id=active.id,status="ACTIVE");db.session.add(membership)
        membership.start_date=date(2017,4,1)
        membership.end_date=None
        membership.status="ACTIVE"
        mandate=Mandate.query.filter_by(name="Octobre 2026 - Mars 2027").first()
        if not mandate:
            mandate=Mandate(name="Octobre 2026 - Mars 2027",start_date=date(2026,10,1),end_date=date(2027,3,31),status="PREPARATION");db.session.add(mandate);db.session.flush()
        role=Role.query.filter(db.func.lower(Role.name)=="président").first()
        if not role:
            role=Role(name="Président");db.session.add(role);db.session.flush()
        assignment=RoleAssignment.query.filter_by(mandate_id=mandate.id,role_id=role.id,member_id=active.id).first()
        if not assignment:
            assignment=RoleAssignment(mandate_id=mandate.id,role_id=role.id,member_id=active.id,status="ACTIVE");db.session.add(assignment)
        db.session.commit()
        return {"status":"ok","memberId":active.id,"systemAdmin":True,"membershipStart":"2017-04-01","mandate":mandate.name,"role":"Président","roleStarts":"2026-10-01","duplicateCandidates":len(candidates)}

    def meeting_payload(m):
        return {"id":m.id,"date":m.date.isoformat(),"startTime":m.start_time.strftime("%H:%M") if m.start_time else None,"type":m.type,"location":m.location,"status":m.status,"notes":m.notes}

    @app.route("/api/meetings",methods=["GET","POST"])
    def meetings():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        if request.method=="POST":
            _,auth_error=require_admin()
            if auth_error:return auth_error
            data=request.get_json(silent=True) or {}
            try: meeting_date=date.fromisoformat(data.get("date",""))
            except ValueError:return {"error":"Date invalide."},400
            allowed={"REGULAR","NO_MEETING","EXTERNAL","HOSTED","JOINT","SPECIAL"}
            meeting_type=data.get("type","REGULAR")
            if meeting_type not in allowed:return {"error":"Type de réunion invalide."},400
            if Meeting.query.filter_by(date=meeting_date).first():return {"error":"Une entrée existe déjà à cette date."},409
            start=None
            if data.get("startTime"):
                try:start=datetime.strptime(data["startTime"],"%H:%M").time()
                except ValueError:return {"error":"Heure invalide."},400
            m=Meeting(date=meeting_date,start_time=start,type=meeting_type,location=(data.get("location") or "").strip() or None,status=data.get("status","PLANNED"),notes=(data.get("notes") or "").strip() or None)
            db.session.add(m);db.session.commit()
            return meeting_payload(m),201
        rows=Meeting.query.order_by(Meeting.date).all()
        return jsonify([meeting_payload(m) for m in rows])

    @app.route("/api/meetings/<int:meeting_id>",methods=["PATCH","DELETE"])
    def meeting_detail(meeting_id):
        _,auth_error=require_admin()
        if auth_error:return auth_error
        m=db.session.get(Meeting,meeting_id)
        if not m:return {"error":"Réunion introuvable."},404
        if request.method=="DELETE":
            db.session.delete(m);db.session.commit();return {"status":"ok"}
        data=request.get_json(silent=True) or {}
        if "date" in data:
            try:m.date=date.fromisoformat(data["date"])
            except ValueError:return {"error":"Date invalide."},400
        if "type" in data:m.type=data["type"]
        if "location" in data:m.location=(data["location"] or "").strip() or None
        if "notes" in data:m.notes=(data["notes"] or "").strip() or None
        if "status" in data:m.status=data["status"]
        if "startTime" in data:
            try:m.start_time=datetime.strptime(data["startTime"],"%H:%M").time() if data["startTime"] else None
            except ValueError:return {"error":"Heure invalide."},400
        db.session.commit();return meeting_payload(m)

    @app.post("/api/meetings/generate-thursdays")
    def generate_thursdays():
        _,auth_error=require_admin()
        if auth_error:return auth_error
        data=request.get_json(silent=True) or {}
        try:start=date.fromisoformat(data.get("startDate",""));end=date.fromisoformat(data.get("endDate",""))
        except ValueError:return {"error":"Dates invalides."},400
        if end<start:return {"error":"La date de fin doit suivre la date de début."},400
        d=start
        while d.weekday()!=3:d+=timedelta(days=1)
        created=0
        while d<=end:
            if not Meeting.query.filter_by(date=d).first():
                db.session.add(Meeting(date=d,start_time=datetime.strptime(data.get("startTime","07:00"),"%H:%M").time(),type="REGULAR",location=(data.get("location") or "").strip() or None,status="PLANNED"));created+=1
            d+=timedelta(days=7)
        db.session.commit()
        return {"status":"ok","created":created}

    with app.app_context():
        db.create_all()
        # Temporary lightweight migration until Alembic is introduced.
        db.session.execute(text("ALTER TABLE user_accounts ADD COLUMN IF NOT EXISTS is_system_admin BOOLEAN NOT NULL DEFAULT FALSE"))
        db.session.commit()
        # Idempotent bootstrap of the first system administrator.
        admin_email=os.getenv("SYSTEM_ADMIN_EMAIL","").strip().lower()
        if admin_email:
            account=UserAccount.query.filter(db.func.lower(UserAccount.email)==admin_email).first()
            if account:
                account.is_system_admin=True
                membership=Membership.query.filter_by(member_id=account.member_id).order_by(Membership.id.asc()).first()
                if not membership:
                    membership=Membership(member_id=account.member_id,status="ACTIVE")
                    db.session.add(membership)
                membership.start_date=date(2017,4,1)
                membership.end_date=None
                membership.status="ACTIVE"
                mandate=Mandate.query.filter_by(name="Octobre 2026 - Mars 2027").first()
                if not mandate:
                    mandate=Mandate(name="Octobre 2026 - Mars 2027",start_date=date(2026,10,1),end_date=date(2027,3,31),status="PREPARATION")
                    db.session.add(mandate);db.session.flush()
                role=Role.query.filter(db.func.lower(Role.name)=="président").first()
                if not role:
                    role=Role(name="Président");db.session.add(role);db.session.flush()
                assignment=RoleAssignment.query.filter_by(mandate_id=mandate.id,role_id=role.id,member_id=account.member_id).first()
                if not assignment:
                    db.session.add(RoleAssignment(mandate_id=mandate.id,role_id=role.id,member_id=account.member_id,status="ACTIVE"))
                db.session.commit()
    return app

app=create_app()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","5000")))
