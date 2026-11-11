import jwt from 'jsonwebtoken';

export const issue = (sub: string) => jwt.sign({ sub }, process.env.JWT_SECRET!, { expiresIn: '15m' });
export const verify = (t: string) => jwt.verify(t, process.env.JWT_SECRET!);
