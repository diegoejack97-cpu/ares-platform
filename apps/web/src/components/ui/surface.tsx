import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";
export function Surface({
  level = 1,
  pressable,
  sheen,
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  level?: 1 | 2 | 3;
  pressable?: boolean;
  sheen?: boolean;
}) {
  return (
    <div
      className={cn(
        `s${level}`,
        pressable && "press",
        sheen && "sheen",
        className,
      )}
      {...props}
    />
  );
}
export function Well({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("well", className)} {...props} />;
}
export function Emboss({
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement>) {
  return <span className={cn("icon-emboss", className)} {...props} />;
}
