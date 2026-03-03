import { Process, Processor } from "@nestjs/bull";
import { MailerService } from "@nestjs-modules/mailer";
import { ConfigService } from "@nestjs/config";
import type { Job } from "bull";


@Processor('mail-queue')
export class MailProcessor {
    constructor(
        private readonly mailerService: MailerService,
        private configService: ConfigService,
    ) { }

    @Process('send-reset-password')
    async handleResetPasswordEmail(job: Job<any>) {
        const { email, subject, otp } = job.data;
        await this.mailerService.sendMail({
            to: email,
            from: this.configService.get<string>('MAIL_FROM') || '"Support Team" <no-reply@domain.com>',
            subject,
            template: 'reset-password',
            context: {
                otp,
                year: new Date().getFullYear(),
            },
        });
    }
}