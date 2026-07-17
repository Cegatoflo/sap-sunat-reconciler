"""
Modelos de datos.

- Sesion:      sesión web (guarda SOLO el usuario, nunca la contraseña).
- Asignacion:  comprobante que un usuario tomó en su bandeja de trabajo.
               La PK compuesta (clave, usuario) permite que el mismo comprobante
               esté en varias bandejas (asignación NO exclusiva).
- Auditoria:   rastro de quién hizo qué y cuándo. En contabilidad es requisito.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKeyConstraint, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Sesion(Base):
    __tablename__ = "sesiones"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    usuario: Mapped[str] = mapped_column(String(50), index=True)
    nombre: Mapped[str] = mapped_column(String(120), default="")
    rol: Mapped[str] = mapped_column(String(20))              # analista | manager
    empresa: Mapped[str] = mapped_column(String(20), index=True)  # código elegido en el login
    creada: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    expira: Mapped[datetime] = mapped_column(DateTime, index=True)


class Asignacion(Base):
    """Asignación EXCLUSIVA: (empresa, clave) es PK, así que un comprobante tiene UN solo dueño.

    Es la base de datos la que garantiza que dos personas no puedan tomar la misma
    factura, aunque hagan clic en el mismo instante (el segundo choca contra la PK).

    `empresa` va en la clave primaria porque el mismo proveedor puede emitirle un
    comprobante con el mismo número a dos empresas distintas (ej. dos empresas del
    mismo grupo comparten un proveedor) — sin esto, chocarían entre sí sin ser el
    mismo documento.
    """

    __tablename__ = "asignaciones"

    empresa: Mapped[str] = mapped_column(String(20), primary_key=True)
    clave: Mapped[str] = mapped_column(String(80), primary_key=True)     # RUC|tipo|SERIE-NUM
    usuario: Mapped[str] = mapped_column(String(50), index=True)         # el dueño

    periodo: Mapped[str] = mapped_column(String(6), index=True)          # yyyymm
    fecha: Mapped[str] = mapped_column(String(10), default="")           # yyyy-mm-dd
    ruc: Mapped[str] = mapped_column(String(11), default="")
    proveedor: Mapped[str] = mapped_column(String(200), default="")
    tipo: Mapped[str] = mapped_column(String(2), default="")             # 01 factura, 07 NC...
    comprobante: Mapped[str] = mapped_column(String(40), default="")
    moneda: Mapped[str] = mapped_column(String(5), default="")
    total: Mapped[float] = mapped_column(Float, default=0.0)

    estado: Mapped[str] = mapped_column(String(15), default="pendiente")  # pendiente | registrada
    nota: Mapped[str] = mapped_column(Text, default="")
    asignada: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    actualizada: Mapped[datetime] = mapped_column(DateTime, default=ahora, onupdate=ahora)

    __table_args__ = (Index("ix_asig_usuario_estado", "usuario", "estado"),)


class Auditoria(Base):
    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    momento: Mapped[datetime] = mapped_column(DateTime, default=ahora, index=True)
    actor: Mapped[str] = mapped_column(String(50), index=True)     # quién lo hizo
    empresa: Mapped[str] = mapped_column(String(20), default="", index=True)
    accion: Mapped[str] = mapped_column(String(30))                # asignar | liberar | revocar | estado | login
    objetivo: Mapped[str] = mapped_column(String(50), default="")  # usuario afectado (en revocar)
    clave: Mapped[str] = mapped_column(String(80), default="")     # comprobante afectado
    detalle: Mapped[str] = mapped_column(Text, default="")
