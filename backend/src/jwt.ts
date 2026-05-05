import jwt from "jsonwebtoken";
import { env } from "./env.js";
import type { UserRole } from "@prisma/client";

export interface JwtPayload {
  sub: string;        // user id
  email: string;
  role: UserRole;
  displayName?: string;
}

export function signToken(payload: JwtPayload): string {
  return jwt.sign(payload, env.JWT_SECRET, {
    expiresIn: env.JWT_EXPIRES_IN as jwt.SignOptions["expiresIn"],
    issuer: "basement",
  });
}

export function verifyToken(token: string): JwtPayload {
  const decoded = jwt.verify(token, env.JWT_SECRET, { issuer: "basement" });
  if (typeof decoded === "string") throw new Error("invalid token");
  return decoded as unknown as JwtPayload;
}
