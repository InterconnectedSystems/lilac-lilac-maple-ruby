import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium transition-opacity duration-150 disabled:pointer-events-none disabled:opacity-40 active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring min-h-11 px-4",
  {
    variants: {
      variant: {
        primary: "bg-accent text-accent-fg hover:opacity-90",
        secondary: "bg-surface-2 text-fg border border-border hover:bg-surface-3",
        ghost: "text-muted hover:text-fg hover:bg-surface-2",
        danger: "bg-crit text-fg-on-crit hover:opacity-90",
      },
    },
    defaultVariants: { variant: "primary" },
  },
);

export function Button({
  className,
  variant,
  asChild,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return <Comp className={cn(buttonVariants({ variant }), className)} {...props} />;
}
